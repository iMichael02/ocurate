import base64
import hashlib
import hmac
import json
import heapq
import logging
import math
import secrets
import threading
import time
from collections import OrderedDict
from typing import NamedTuple

from app.log_setup import log_event

logger = logging.getLogger(__name__)


class TokenError(Exception):
    """A refused Session token. `code` is safe to log and to send back."""

    code = "invalid_token"


class InvalidSignature(TokenError):
    """The signature does not match, or the token is not in our format."""

    code = "invalid_signature"


class TokenExpired(TokenError):

    code = "expired"


class TokenAlreadyUsed(TokenError):

    code = "already_used"


class UnknownSession(TokenError):
    """Signed by us but not pending here, e.g. issued before a restart."""

    code = "unknown_session"


class TooManySessions(Exception):
    """Too many Sessions are waiting for their token to be used."""


class IssuedToken(NamedTuple):

    session_id: str
    token: str
    expires_at: int


class SessionGrant(NamedTuple):

    session_id: str
    passage_id: str


def _b64encode(data):

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text):

    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class TokenStore:
    """Creates Sessions and their tokens, and lets each token be used once.

    Pending and used tokens are kept in this process's memory only. So this
    works with a single worker process, and pending Sessions are lost on
    restart (see docs/t9-sessions.md). `max_pending` caps how many Sessions
    can wait for their token at once.
    """

    def __init__(self, secret, ttl_seconds, clock=time.time, max_pending=None):

        if ttl_seconds <= 0:
            raise ValueError("token lifetime must be positive")

        self._secret = secret.encode("utf-8") if secret else None
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self.max_pending = max_pending
        self._lock = threading.Lock()

        # token id -> (session id, passage id, expiry). Every token has the same
        # lifetime, so insertion order is expiry order and expired entries are
        # dropped from the front.
        self._pending = OrderedDict()
        # token id -> expiry, plus a heap of (expiry, token id) to drop them in
        # order. Dropped once expired, since the expiry check then refuses a
        # replay anyway.
        self._used = {}
        self._used_expiry = []

    @property
    def configured(self):

        return self._secret is not None

    def create_session(self, passage_id):

        if not self.configured:
            raise RuntimeError("token secret is not set")

        session_id = secrets.token_urlsafe(16)
        token_id = secrets.token_urlsafe(16)

        with self._lock:
            now = self._clock()
            self._remove_expired(now)

            if self.max_pending is not None and len(self._pending) >= self.max_pending:
                raise TooManySessions()

            # Rounded up so the token lives at least `ttl_seconds`.
            expires_at = math.ceil(now + self.ttl_seconds)
            self._pending[token_id] = (session_id, passage_id, expires_at)

        # Only the token id and expiry are signed; the Session and Passage
        # come from the pending entry, which is the single source of truth.
        payload = {"exp": expires_at, "jti": token_id}

        return IssuedToken(session_id, self._sign(payload), expires_at)

    def verify_and_consume_token(self, token):
        """Checks `token` and marks it used. Returns a SessionGrant or raises
        InvalidSignature, TokenExpired, TokenAlreadyUsed or UnknownSession.

        Everything after the signature check runs under one lock, so two
        connections racing with the same token cannot both get through.
        """

        expires_at, token_id = self._verify_signature(token)

        with self._lock:
            now = self._clock()

            if now >= expires_at:
                raise TokenExpired()

            self._remove_expired(now)

            if token_id in self._used:
                raise TokenAlreadyUsed()

            entry = self._pending.pop(token_id, None)
            if entry is None:
                raise UnknownSession()

            session_id, passage_id, _ = entry
            self._used[token_id] = expires_at
            heapq.heappush(self._used_expiry, (expires_at, token_id))

        return SessionGrant(session_id, passage_id)

    def pending_count(self):

        with self._lock:
            self._remove_expired(self._clock())
            return len(self._pending)

    def used_count(self):

        with self._lock:
            self._remove_expired(self._clock())
            return len(self._used)

    def _signature(self, payload_part):

        digest = hmac.new(self._secret, payload_part.encode("ascii"), hashlib.sha256).digest()

        return _b64encode(digest)

    def _sign(self, payload):

        payload_part = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

        return payload_part + "." + self._signature(payload_part)

    def _verify_signature(self, token):

        if not self.configured:
            raise InvalidSignature()

        try:
            payload_part, signature_part = token.split(".")

            # Compare the encoded text, not decoded bytes: base64 decoding
            # skips stray characters, so a changed token could still match.
            expected = self._signature(payload_part).encode("ascii")
            if not hmac.compare_digest(expected, signature_part.encode("utf-8")):
                raise InvalidSignature()

            claims = json.loads(_b64decode(payload_part))
            expires_at, token_id = claims["exp"], claims["jti"]
            if not isinstance(expires_at, int) or not isinstance(token_id, str):
                raise InvalidSignature()
            return expires_at, token_id
        except (ValueError, KeyError, TypeError, AttributeError):
            raise InvalidSignature() from None

    def _remove_expired(self, now):

        while self._pending:
            token_id, entry = next(iter(self._pending.items()))
            if entry[2] > now:
                break
            del self._pending[token_id]

        while self._used_expiry and self._used_expiry[0][0] <= now:
            _, token_id = heapq.heappop(self._used_expiry)
            del self._used[token_id]


def build_token_store(settings, clock=time.time):

    secret = settings.token_secret

    if secret is None and settings.dev_mode:
        secret = secrets.token_urlsafe(32)
        # The secret and the token tables live in this process only: no --reload, one worker.
        log_event(logger, "token_secret_generated", logging.WARNING, dev_mode=True, note="single_process_only")
    elif secret is None:
        log_event(logger, "session_creation_disabled", logging.WARNING, reason="token_secret_unset")

    return TokenStore(secret, settings.token_ttl_seconds, clock, settings.max_concurrent_sessions)
