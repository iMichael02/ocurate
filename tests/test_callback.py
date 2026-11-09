import asyncio
import base64
import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

import callback
from app import create_app
from callback import CallbackConfigError, CallbackSender, build_body, load_callback_config, sign
from config import Settings
from session_manager import Outcome

# From the Standard Webhooks reference test suite (github.com/standard-webhooks/standard-webhooks).
VECTOR_SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
VECTOR_ID = "msg_p5jXN8AQM9LWM0D4loKWxJek"
VECTOR_TIMESTAMP = 1614265330
VECTOR_BODY = b'{"test": 2432232314}'
VECTOR_SIGNATURE = "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="

SECRET = "whsec_" + base64.b64encode(bytes(range(32))).decode()
URL = "https://web.example/results"
START = 1760000000.0

RESULT = {
    "elapsed_seconds": 10.0,
    "cpm": 108.0,
    "wpm": 18.0,
    "saccades": 17,
    "regressions": 1,
    "skipped_characters": 0,
    "sequence": [{"row": 0, "col": 0}, {"row": 0, "col": 1}],
}


def completed(session_id="Xq3n0d5bWm1Kz7yQ2r8T4A"):

    return Outcome("completed", session_id, "default", result=dict(RESULT))


def abandoned(session_id="abandoned-1"):

    return Outcome("abandoned", session_id, "default", reason="quit")


class FakeClock:

    def __init__(self):

        self.now = START
        self.sleeps = []

    def __call__(self):

        return self.now

    async def sleep(self, seconds):

        self.sleeps.append(seconds)
        self.now += seconds
        await asyncio.sleep(0)


def responder(*answers):
    """A MockTransport handler giving each answer in turn (the last repeats):
    an int is a status code, an exception is raised as a network error."""

    requests = []

    def handle(request):

        requests.append(request)
        answer = answers[min(len(requests), len(answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(answer)

    return handle, requests


def run(answers, outcomes=None, rng=lambda: 0.0, **settings):
    """Submits the outcomes to a started sender and waits until nothing is pending."""

    handle, requests = responder(*answers)
    clock = FakeClock()

    async def scenario():

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        sender = CallbackSender(Settings(callback_url=URL, callback_secret=SECRET, **settings),
                                client=client, clock=clock, sleep=clock.sleep, rng=rng)
        await sender.start()
        for outcome in outcomes or [completed()]:
            sender.submit(outcome)
        while sender.pending:
            await asyncio.sleep(0)
        await sender.stop()
        await client.aclose()

    asyncio.run(scenario())

    return requests, clock


# --- body and signature -------------------------------------------------------

def test_signature_matches_the_standard_webhooks_test_vector():

    assert sign(VECTOR_SECRET, VECTOR_ID, VECTOR_TIMESTAMP, VECTOR_BODY) == VECTOR_SIGNATURE


def test_sign_accepts_the_decoded_key():

    key = base64.b64decode(VECTOR_SECRET.removeprefix("whsec_"))

    assert sign(key, VECTOR_ID, VECTOR_TIMESTAMP, VECTOR_BODY) == VECTOR_SIGNATURE


def test_body_is_the_documented_contract():

    assert json.loads(build_body(completed())) == {
        "session_id": "Xq3n0d5bWm1Kz7yQ2r8T4A",
        "passage_id": "default",
        "status": "completed",
        "result": RESULT,
    }


def test_body_refuses_abandoned_outcomes():

    with pytest.raises(ValueError):
        build_body(abandoned())


# --- sending ------------------------------------------------------------------

def test_success_sends_one_signed_request():

    requests, _ = run([200])

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == URL
    assert request.headers["content-type"] == "application/json"
    assert request.headers["webhook-id"] == "Xq3n0d5bWm1Kz7yQ2r8T4A"
    assert request.headers["webhook-timestamp"] == str(int(START))
    assert request.content == build_body(completed())
    assert request.headers["webhook-signature"] == sign(SECRET, "Xq3n0d5bWm1Kz7yQ2r8T4A", int(START), request.content)


def test_abandoned_sessions_send_nothing():

    requests, _ = run([200], outcomes=[abandoned()])

    assert requests == []


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_retryable_status_is_retried_with_the_same_body(status):

    requests, clock = run([status, status, 204])

    assert len(requests) == 3
    assert {r.content for r in requests} == {build_body(completed())}
    assert {r.headers["webhook-id"] for r in requests} == {"Xq3n0d5bWm1Kz7yQ2r8T4A"}
    # A fresh timestamp and signature on each attempt.
    assert [r.headers["webhook-timestamp"] for r in requests] == [str(int(START)), str(int(START + 1)), str(int(START + 3))]
    for request in requests:
        timestamp = int(request.headers["webhook-timestamp"])
        assert request.headers["webhook-signature"] == sign(SECRET, request.headers["webhook-id"], timestamp, request.content)


@pytest.mark.parametrize("error", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
def test_network_errors_are_retried(error):

    requests, _ = run([error, 200])

    assert len(requests) == 2


@pytest.mark.parametrize("status", [301, 400, 401, 404, 422])
def test_other_statuses_are_not_retried(status, caplog):

    with caplog.at_level(logging.INFO, logger="callback"):
        requests, clock = run([status])

    assert len(requests) == 1
    assert clock.sleeps == []
    assert any(m.startswith("callback_rejected") and f"status={status}" in m for m in caplog.messages)


def test_backoff_doubles_up_to_sixty_seconds_without_jitter():

    _, clock = run([500] * 9 + [200])

    assert clock.sleeps == [1, 2, 4, 8, 16, 32, 60, 60, 60]


def test_jitter_shortens_each_delay_by_at_most_twenty_percent():

    _, clock = run([500] * 7 + [200], rng=lambda: 1.0)

    assert clock.sleeps == pytest.approx([0.8, 1.6, 3.2, 6.4, 12.8, 25.6, 48.0])


def test_gives_up_after_fifteen_minutes(caplog):

    with caplog.at_level(logging.INFO, logger="callback"):
        requests, clock = run([503])

    # 1+2+...+32 = 63 s, then 60 s waits while the next attempt, with its 5 s
    # timeout, still ends inside 900 s.
    assert sum(clock.sleeps) + 5 <= 15 * 60
    assert sum(clock.sleeps) + 60 + 5 > 15 * 60
    assert len(requests) == len(clock.sleeps) + 1
    assert len(requests) == 20
    assert caplog.messages[-1].startswith("callback_dropped session_id=Xq3n0d5bWm1Kz7yQ2r8T4A attempt=20 status=503")


def test_retry_window_ignores_wall_clock_jumps():

    clock = FakeClock()
    monotonic = FakeClock()
    calls = []

    def handle(request):

        calls.append(request)
        # The wall clock jumps an hour ahead after the first attempt.
        clock.now += 3600
        return httpx.Response(500 if len(calls) < 3 else 200)

    async def sleep(seconds):

        monotonic.now += seconds
        await asyncio.sleep(0)

    async def scenario():

        sender = CallbackSender(Settings(callback_url=URL, callback_secret=SECRET),
                                client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
                                clock=clock, sleep=sleep, rng=lambda: 0.0, monotonic=monotonic)
        await sender.start()
        sender.submit(completed())
        while sender.pending:
            await asyncio.sleep(0)
        await sender.stop()

    asyncio.run(scenario())

    assert len(calls) == 3
    # webhook-timestamp still follows the wall clock.
    assert calls[1].headers["webhook-timestamp"] == str(int(START + 3600))


class HangingClient:
    """Answers its first POST never (a server that stalls mid-response), then 200."""

    def __init__(self):

        self.calls = 0

    async def post(self, url, **kwargs):

        self.calls += 1
        if self.calls == 1:
            await asyncio.Event().wait()
        return httpx.Response(200)


def test_a_stalled_attempt_is_cut_off_and_retried(monkeypatch, caplog):

    monkeypatch.setattr(callback, "REQUEST_TIMEOUT_SECONDS", 0.05)
    client = HangingClient()
    clock = FakeClock()

    async def scenario():

        sender = CallbackSender(Settings(callback_url=URL, callback_secret=SECRET),
                                client=client, clock=clock, sleep=clock.sleep, rng=lambda: 0.0)
        await sender.start()
        sender.submit(completed())
        while sender.pending:
            await asyncio.sleep(0.01)
        await sender.stop()

    with caplog.at_level(logging.INFO, logger="callback"):
        asyncio.run(scenario())

    assert client.calls == 2
    assert any(m.startswith("callback_retry") and "error=AttemptTimeout" in m for m in caplog.messages)


def test_submit_after_stop_is_dropped_not_left_pending(caplog):

    async def scenario():

        sender = CallbackSender(Settings(callback_url=URL, callback_secret=SECRET),
                                client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))))
        await sender.start()
        await sender.stop()
        sender.submit(completed())
        return sender.pending

    with caplog.at_level(logging.INFO, logger="callback"):
        assert asyncio.run(scenario()) == 0

    assert caplog.messages[-1] == "callback_dropped session_id=Xq3n0d5bWm1Kz7yQ2r8T4A reason=shutdown"


def test_a_retrying_callback_does_not_hold_up_the_next_one():

    handle_calls = []

    def handle(request):

        session_id = request.headers["webhook-id"]
        handle_calls.append(session_id)
        return httpx.Response(500 if session_id == "slow" and handle_calls.count("slow") < 3 else 200)

    clock = FakeClock()

    async def scenario():

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        sender = CallbackSender(Settings(callback_url=URL, callback_secret=SECRET),
                                client=client, clock=clock, sleep=clock.sleep, rng=lambda: 0.0)
        await sender.start()
        sender.submit(completed("slow"))
        sender.submit(completed("fast"))
        while sender.pending:
            await asyncio.sleep(0)
        await sender.stop()

    asyncio.run(scenario())

    assert handle_calls.index("fast") < len(handle_calls) - 1
    assert handle_calls.count("slow") == 3


def test_submit_does_no_io_and_returns_immediately():

    handle, requests = responder(200)

    async def scenario():

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        sender = CallbackSender(Settings(callback_url=URL, callback_secret=SECRET), client=client)
        await sender.start()
        sender.submit(completed())
        sent_during_submit = len(requests)
        await sender.stop()
        return sent_during_submit

    assert asyncio.run(scenario()) == 0


def test_queue_drops_the_oldest_past_its_cap(monkeypatch, caplog):

    monkeypatch.setattr(callback, "MAX_PENDING", 3)

    async def scenario():

        sender = CallbackSender(Settings(callback_url=URL, callback_secret=SECRET),
                                client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))))
        # Not started: everything stays queued.
        for n in range(5):
            sender.submit(completed(f"s{n}"))
        return [d.session_id for d in sender._pending]

    with caplog.at_level(logging.INFO, logger="callback"):
        assert asyncio.run(scenario()) == ["s2", "s3", "s4"]

    dropped = [m for m in caplog.messages if m.startswith("callback_dropped")]
    assert dropped == ["callback_dropped session_id=s0 reason=queue_full",
                       "callback_dropped session_id=s1 reason=queue_full"]


def test_default_queue_cap_is_one_thousand():

    assert callback.MAX_PENDING == 1000


def test_callbacks_queued_before_start_are_sent_once_started():

    handle, requests = responder(200)

    async def scenario():

        sender = CallbackSender(Settings(callback_url=URL, callback_secret=SECRET),
                                client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
        sender.submit(completed())
        await sender.start()
        while sender.pending:
            await asyncio.sleep(0)
        await sender.stop()

    asyncio.run(scenario())

    assert len(requests) == 1


def test_stop_drops_retrying_callbacks(caplog):

    clock = FakeClock()

    async def never(seconds):
        await asyncio.Event().wait()

    async def scenario():

        sender = CallbackSender(Settings(callback_url=URL, callback_secret=SECRET),
                                client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))),
                                clock=clock, sleep=never)
        await sender.start()
        sender.submit(completed())
        for _ in range(20):
            await asyncio.sleep(0)
        await sender.stop()
        return sender.pending

    with caplog.at_level(logging.INFO, logger="callback"):
        assert asyncio.run(scenario()) == 0

    assert caplog.messages[-1] == "callback_dropped session_id=Xq3n0d5bWm1Kz7yQ2r8T4A reason=shutdown"


def test_owned_client_has_a_five_second_timeout_and_no_redirects():

    async def scenario():

        sender = CallbackSender(Settings(callback_url=URL, callback_secret=SECRET))
        await sender.start()
        client = sender._client
        await sender.stop()
        return client

    client = asyncio.run(scenario())

    assert client.timeout == httpx.Timeout(5.0)
    assert client.follow_redirects is False
    assert client.is_closed


# --- configuration ------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://web.example/results",
    "http://localhost:8000/results",
    "http://127.0.0.1/results",
])
def test_accepted_urls(url):

    assert load_callback_config(Settings(callback_url=url, callback_secret=SECRET)).url == url


@pytest.mark.parametrize("url", [
    "http://web.example/results",
    "http://localhost.web.example/results",
    "ftp://web.example/results",
    "web.example/results",
    "https:///results",
])
def test_rejected_urls(url):

    with pytest.raises(CallbackConfigError):
        load_callback_config(Settings(callback_url=url, callback_secret=SECRET))


@pytest.mark.parametrize("secret", [
    None,
    "",
    "MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw",
    "whsec_not*base64!",
    "whsec_" + base64.b64encode(b"short").decode(),
])
def test_url_without_a_usable_secret_refuses_to_start(secret):

    with pytest.raises(CallbackConfigError):
        create_app(Settings(callback_url=URL, callback_secret=secret))


def test_secret_is_decoded_to_the_hmac_key():

    config = load_callback_config(Settings(callback_url=URL, callback_secret=SECRET))

    assert config.key == bytes(range(32))
    assert SECRET not in repr(config)


def test_config_errors_do_not_echo_the_secret():

    bad = "whsec_" + base64.b64encode(b"tiny-secret").decode()

    with pytest.raises(CallbackConfigError) as error:
        load_callback_config(Settings(callback_url=URL, callback_secret=bad))

    assert bad not in str(error.value)


@pytest.mark.parametrize("settings", [Settings(), Settings(callback_secret=SECRET)])
def test_without_url_callbacks_are_disabled_with_a_warning(settings, caplog):

    with caplog.at_level(logging.WARNING, logger="callback"):
        sender = CallbackSender(settings)

    assert not sender.enabled
    assert any(m.startswith("callback_disabled") for m in caplog.messages)

    async def scenario():
        await sender.start()
        sender.submit(completed())
        pending = sender.pending
        await sender.stop()
        return pending

    assert asyncio.run(scenario()) == 0


# --- app wiring ---------------------------------------------------------------

def test_app_wires_session_end_to_the_sender_and_runs_it_with_the_lifespan(monkeypatch):

    handle, requests = responder(200)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(callback.httpx, "AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs))

    app = create_app(Settings(callback_url=URL, callback_secret=SECRET))
    sender = app.state.callbacks

    assert app.state.on_session_finished == sender.submit

    with TestClient(app) as client:
        assert sender._running
        client.portal.call(lambda: _submit_and_drain(sender))

    assert not sender._running
    assert len(requests) == 1


async def _submit_and_drain(sender):

    sender.submit(abandoned())
    sender.submit(completed())
    while sender.pending:
        await asyncio.sleep(0)


# --- logging ------------------------------------------------------------------

def test_logs_hold_no_secret_signature_or_body(caplog):

    with caplog.at_level(logging.DEBUG):
        requests, _ = run([httpx.ConnectError("refused"), 503, 400])

    signatures = [r.headers["webhook-signature"] for r in requests]
    events = [m.split(" ")[0] for m in caplog.messages if m.startswith("callback_")]

    assert events == ["callback_retry", "callback_retry", "callback_rejected"]
    text = "\n".join(caplog.messages)
    assert SECRET not in text
    assert SECRET.removeprefix("whsec_") not in text
    for signature in signatures:
        assert signature not in text
        assert signature.removeprefix("v1,") not in text
    assert "108.0" not in text
    assert '"sequence"' not in text
    assert "passage_id" not in text
