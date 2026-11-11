"""The signed result callback: POSTs each completed Session's result to the
web server, signed per Standard Webhooks, retried in the background.
See docs/result-callback.md."""

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import logging
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlsplit

import httpx

from app.log_setup import log_event
from app.schemas import protocol

logger = logging.getLogger(__name__)

SECRET_PREFIX = "whsec_"
MIN_SECRET_BYTES = 24
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})

REQUEST_TIMEOUT_SECONDS = 5.0
FIRST_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 60.0
JITTER = 0.2
RETRY_WINDOW_SECONDS = 15 * 60
MAX_PENDING = 1000


class CallbackConfigError(ValueError):
    """OCURATE_CALLBACK_URL / OCURATE_CALLBACK_SECRET are unusable; the app
    refuses to start rather than send unsigned or plaintext results."""


@dataclass(frozen=True)
class CallbackConfig:

    url: str
    key: bytes = field(repr=False)


def decode_secret(secret):
    """The HMAC key held in a `whsec_<base64>` secret."""

    if not secret.startswith(SECRET_PREFIX):
        raise CallbackConfigError(f"OCURATE_CALLBACK_SECRET must start with {SECRET_PREFIX!r}")

    try:
        key = base64.b64decode(secret[len(SECRET_PREFIX):], validate=True)
    except binascii.Error:
        raise CallbackConfigError("OCURATE_CALLBACK_SECRET is not valid base64 after the prefix") from None

    if len(key) < MIN_SECRET_BYTES:
        raise CallbackConfigError(f"OCURATE_CALLBACK_SECRET must hold at least {MIN_SECRET_BYTES} bytes")

    return key


def check_url(url):

    parts = urlsplit(url)

    if parts.scheme == "https" and parts.hostname:
        return
    if parts.scheme == "http" and parts.hostname in LOCAL_HOSTS:
        return

    raise CallbackConfigError("OCURATE_CALLBACK_URL must be https:// (http:// only for localhost or 127.0.0.1)")


def load_callback_config(settings):
    """The callback target, or None when callbacks are switched off."""

    if not settings.callback_url:
        reason = "callback_secret_without_url" if settings.callback_secret else "callback_url_unset"
        log_event(logger, "callback_disabled", logging.WARNING, reason=reason)
        return None

    check_url(settings.callback_url)

    if not settings.callback_secret:
        raise CallbackConfigError("OCURATE_CALLBACK_SECRET is required when OCURATE_CALLBACK_URL is set")

    return CallbackConfig(settings.callback_url, decode_secret(settings.callback_secret))


def build_body(outcome):
    """The exact bytes POSTed for a completed Session's Outcome."""

    if outcome.kind != "completed":
        raise ValueError(f"only completed Sessions are reported, got {outcome.kind!r}")

    body = {
        "session_id": outcome.session_id,
        "passage_id": outcome.passage_id,
        "status": "completed",
        # Through protocol.Result so the web server stores what the Learner saw.
        "result": protocol.Result(**outcome.result).model_dump(),
    }

    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def sign(secret, msg_id, timestamp, body):
    """The `webhook-signature` header value. `secret` is the `whsec_` string or
    the key it decodes to; `body` is the raw bytes sent."""

    key = decode_secret(secret) if isinstance(secret, str) else secret
    signed = f"{msg_id}.{timestamp}.".encode("utf-8") + body
    digest = hmac.new(key, signed, hashlib.sha256).digest()

    return "v1," + base64.b64encode(digest).decode("ascii")


def is_retryable(status):
    """None stands for no answer (timeout, connection error)."""

    return status is None or status in (408, 429) or status >= 500


@dataclass(eq=False)
class Delivery:

    session_id: str
    body: bytes = field(repr=False)
    task: Optional[asyncio.Task] = None


class CallbackSender:
    """Sends completed Sessions' results in the background.

    `submit` only queues, so the WebSocket handler never waits on the web
    server. Each queued result gets its own task that retries with backoff;
    the queue counts results waiting or retrying and drops the oldest past
    MAX_PENDING. Nothing outlives the process (docs/result-callback.md).
    """

    def __init__(self, settings, client=None, clock=time.time, sleep=asyncio.sleep, rng=random.random,
                 monotonic=None):

        self.config = load_callback_config(settings)
        self._client = client
        self._owns_client = client is None
        # `clock` stamps webhook-timestamp (unix seconds); the retry window is
        # measured on `monotonic` so a wall-clock jump cannot stretch or cut it.
        self._clock = clock
        self._monotonic = monotonic or (time.monotonic if clock is time.time else clock)
        self._sleep = sleep
        self._rng = rng
        self._pending = deque()
        self._running = False
        self._stopped = False
        self.dropped = 0

    def _drop(self, session_id, level, reason, **fields):
        """Logs a lost result and counts it (`dropped`)."""

        self.dropped += 1
        log_event(logger, "callback_dropped", level, session_id=session_id, reason=reason, **fields)

    @property
    def enabled(self):

        return self.config is not None

    @property
    def pending(self):

        return len(self._pending)

    async def start(self):

        if not self.enabled:
            return

        if self._client is None:
            self._client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False)

        self._running = True

        for delivery in self._pending:
            self._launch(delivery)

    async def stop(self):
        """Cancels whatever is still pending: a restart drops those results."""

        self._running = False
        self._stopped = True
        tasks = []

        while self._pending:
            delivery = self._pending.popleft()
            self._drop(delivery.session_id, logging.WARNING, "shutdown")
            if delivery.task is not None:
                delivery.task.cancel()
                tasks.append(delivery.task)

        await asyncio.gather(*tasks, return_exceptions=True)

        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def submit(self, outcome):
        """Queues a finished Session's result and returns at once. Abandoned
        Sessions are ignored. Call it from the event loop."""

        if not self.enabled or outcome.kind != "completed":
            return

        try:
            body = build_body(outcome)
        except (ValueError, TypeError) as error:
            # Never let a malformed Outcome break the WebSocket teardown that calls this.
            self._drop(outcome.session_id, logging.ERROR, "invalid_result", error=type(error).__name__)
            return

        if self._stopped:
            self._drop(outcome.session_id, logging.WARNING, "shutdown")
            return

        if len(self._pending) >= MAX_PENDING:
            oldest = self._pending.popleft()
            self._drop(oldest.session_id, logging.WARNING, "queue_full")
            if oldest.task is not None:
                oldest.task.cancel()

        delivery = Delivery(outcome.session_id, body)
        self._pending.append(delivery)

        if self._running:
            self._launch(delivery)

    def _launch(self, delivery):

        delivery.task = asyncio.get_running_loop().create_task(self._deliver(delivery))
        delivery.task.add_done_callback(lambda task: self._forget(delivery, task))

    def _forget(self, delivery, task):

        try:
            self._pending.remove(delivery)
        except ValueError:
            pass  # already dropped

        if not task.cancelled() and task.exception() is not None:
            self._drop(delivery.session_id, logging.ERROR, "internal_error", error=type(task.exception()).__name__)

    async def _deliver(self, delivery):

        started = self._monotonic()
        delay = FIRST_DELAY_SECONDS
        attempt = 0

        while True:
            attempt += 1
            status, error = await self._attempt(delivery)

            if status is not None and 200 <= status < 300:
                log_event(logger, "callback_sent", session_id=delivery.session_id, attempt=attempt, status=status)
                return

            if not is_retryable(status):
                # Redirects are never followed; a 3xx usually means a wrong URL (e.g. http instead of https).
                hint = {"hint": "redirects_not_followed"} if status is not None and 300 <= status < 400 else {}
                log_event(logger, "callback_rejected", logging.WARNING, session_id=delivery.session_id,
                          attempt=attempt, status=status, **hint)
                return

            # Jitter only shortens the wait, so no delay passes MAX_DELAY_SECONDS.
            wait = delay * (1 - JITTER * self._rng())

            # The next attempt, timeout included, must end inside the window.
            if self._monotonic() + wait + REQUEST_TIMEOUT_SECONDS - started > RETRY_WINDOW_SECONDS:
                self._drop(delivery.session_id, logging.WARNING, "retry_window_exceeded",
                           attempt=attempt, status=status, error=error)
                return

            log_event(logger, "callback_retry", logging.WARNING, session_id=delivery.session_id,
                      attempt=attempt, status=status, error=error, delay=round(wait, 3))

            await self._sleep(wait)
            delay = min(delay * 2, MAX_DELAY_SECONDS)

    async def _attempt(self, delivery):
        """One POST. Returns (status, None), or (None, error type) when there was no answer."""

        timestamp = int(self._clock())
        headers = {
            "content-type": "application/json",
            "webhook-id": delivery.session_id,
            "webhook-timestamp": str(timestamp),
            "webhook-signature": sign(self.config.key, delivery.session_id, timestamp, delivery.body),
        }

        try:
            # httpx's timeout applies to each phase (connect, write, read, pool)
            # separately; this caps the whole attempt at 5 s.
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                response = await self._client.post(
                    self.config.url,
                    content=delivery.body,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    follow_redirects=False,
                )
        except httpx.HTTPError as error:
            return None, type(error).__name__
        except TimeoutError:
            return None, "AttemptTimeout"

        return response.status_code, None
