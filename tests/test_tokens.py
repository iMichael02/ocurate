import base64
import json
import logging
import sys
import threading

import pytest

from config import Settings
from tokens import (InvalidSignature, SessionGrant, TokenAlreadyUsed, TokenExpired, TokenStore,
                    UnknownSession, build_token_store)

SECRET = "test-token-secret"


class FakeClock:

    def __init__(self, now=1000.0):

        self.now = now

    def __call__(self):

        return self.now


def make_store(clock=None, ttl=60):

    return TokenStore(SECRET, ttl, clock or FakeClock())


def decode_payload(token):

    payload_part = token.split(".")[0]

    return json.loads(base64.urlsafe_b64decode(payload_part + "=" * (-len(payload_part) % 4)))


def encode_payload(claims):

    raw = json.dumps(claims, separators=(",", ":")).encode("utf-8")

    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def test_token_holds_session_id_passage_id_expiry_and_token_id():

    issued = make_store(FakeClock(1000.0)).create_session("default")

    claims = decode_payload(issued.token)

    assert claims["sid"] == issued.session_id
    assert claims["pid"] == "default"
    assert claims["exp"] == 1060 == issued.expires_at
    assert claims["jti"]


def test_session_ids_and_token_ids_are_unique():

    store = make_store()

    issued = [store.create_session("default") for _ in range(50)]

    assert len({i.session_id for i in issued}) == 50
    assert len({decode_payload(i.token)["jti"] for i in issued}) == 50


def test_valid_token_returns_session_and_passage():

    store = make_store()
    issued = store.create_session("default")

    grant = store.verify_and_consume_token(issued.token)

    assert grant == SessionGrant(issued.session_id, "default")


def test_second_use_is_refused():

    store = make_store()
    issued = store.create_session("default")
    store.verify_and_consume_token(issued.token)

    with pytest.raises(TokenAlreadyUsed):
        store.verify_and_consume_token(issued.token)


@pytest.fixture
def frequent_thread_switches():

    # Without this the GIL runs each thread to the end and the race never
    # shows up. With it, removing the lock makes this test fail.
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    yield
    sys.setswitchinterval(old)


def test_simultaneous_uses_let_exactly_one_through(frequent_thread_switches):

    store = make_store()
    threads_per_token = 8

    for _ in range(25):
        token = store.create_session("default").token
        barrier = threading.Barrier(threads_per_token)
        outcomes = []

        def connect():
            barrier.wait()
            try:
                store.verify_and_consume_token(token)
                outcomes.append("ok")
            except Exception as error:
                outcomes.append(getattr(error, "code", repr(error)))

        threads = [threading.Thread(target=connect) for _ in range(threads_per_token)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sorted(outcomes) == ["already_used"] * (threads_per_token - 1) + ["ok"]


def test_token_works_until_just_before_expiry():

    clock = FakeClock(1000.0)
    store = make_store(clock)
    issued = store.create_session("default")

    clock.now = 1059.9

    assert store.verify_and_consume_token(issued.token).session_id == issued.session_id


@pytest.mark.parametrize("later", [1060.0, 5000.0])
def test_expired_token_is_refused(later):

    clock = FakeClock(1000.0)
    store = make_store(clock)
    issued = store.create_session("default")

    clock.now = later

    with pytest.raises(TokenExpired):
        store.verify_and_consume_token(issued.token)


def test_changed_payload_is_refused():

    store = make_store()
    store.create_session("other")
    issued = store.create_session("default")
    signature_part = issued.token.split(".")[1]

    claims = decode_payload(issued.token)
    claims["pid"] = "other"

    with pytest.raises(InvalidSignature):
        store.verify_and_consume_token(encode_payload(claims) + "." + signature_part)


def test_pushed_back_expiry_is_refused():

    clock = FakeClock(1000.0)
    store = make_store(clock)
    issued = store.create_session("default")
    signature_part = issued.token.split(".")[1]

    claims = decode_payload(issued.token)
    claims["exp"] = 9999
    clock.now = 2000.0

    with pytest.raises(InvalidSignature):
        store.verify_and_consume_token(encode_payload(claims) + "." + signature_part)


def test_changed_signature_is_refused():

    store = make_store()
    token = store.create_session("default").token
    last = token[-1]

    with pytest.raises(InvalidSignature):
        store.verify_and_consume_token(token[:-1] + ("A" if last != "A" else "B"))


@pytest.mark.parametrize("extra", ["!", "=", "==", " "])
def test_extra_characters_in_signature_are_refused(extra):

    store = make_store()
    token = store.create_session("default").token

    with pytest.raises(InvalidSignature):
        store.verify_and_consume_token(token + extra)


def test_token_signed_with_another_secret_is_refused():

    other = TokenStore("another-secret", 60, FakeClock())
    token = other.create_session("default").token

    with pytest.raises(InvalidSignature):
        make_store().verify_and_consume_token(token)


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "é.é", ".", None, 42])
def test_malformed_token_is_refused(token):

    with pytest.raises(InvalidSignature):
        make_store().verify_and_consume_token(token)


def test_token_from_before_a_restart_is_unknown():

    clock = FakeClock()
    token = make_store(clock).create_session("default").token

    with pytest.raises(UnknownSession):
        make_store(clock).verify_and_consume_token(token)


def test_errors_have_distinct_codes():

    codes = {error.code for error in (InvalidSignature, TokenExpired, TokenAlreadyUsed, UnknownSession)}

    assert codes == {"invalid_signature", "expired", "already_used", "unknown_session"}


def test_expired_entries_are_removed():

    clock = FakeClock(1000.0)
    store = make_store(clock)
    used = store.create_session("default")
    for _ in range(3):
        store.create_session("default")
    store.verify_and_consume_token(used.token)

    assert store.pending_count() == 3
    assert store.used_count() == 1

    clock.now = 1060.0

    assert store.pending_count() == 0
    assert store.used_count() == 0


def test_store_without_secret_creates_and_accepts_nothing():

    store = TokenStore(None, 60)
    token = make_store().create_session("default").token

    assert store.configured is False
    with pytest.raises(RuntimeError):
        store.create_session("default")
    with pytest.raises(InvalidSignature):
        store.verify_and_consume_token(token)


@pytest.mark.parametrize("ttl", [0, -5])
def test_lifetime_must_be_positive(ttl):

    with pytest.raises(ValueError):
        TokenStore(SECRET, ttl)


def test_build_uses_lifetime_from_settings():

    clock = FakeClock(1000.0)
    store = build_token_store(Settings(token_secret=SECRET, token_ttl_seconds=15), clock)

    assert store.create_session("default").expires_at == 1015


def test_build_without_secret_outside_dev_mode_is_not_configured(caplog):

    with caplog.at_level(logging.WARNING, logger="tokens"):
        store = build_token_store(Settings())

    assert store.configured is False
    assert caplog.messages == ["session_creation_disabled reason=token_secret_unset"]


def test_build_in_dev_mode_generates_a_secret_and_says_so(caplog):

    with caplog.at_level(logging.WARNING, logger="tokens"):
        store = build_token_store(Settings(dev_mode=True))
    issued = store.create_session("default")

    assert store.verify_and_consume_token(issued.token).session_id == issued.session_id
    assert caplog.messages == ["token_secret_generated dev_mode=True"]
    assert store._secret.decode("utf-8") not in caplog.text


def test_dev_mode_keeps_a_secret_that_is_set():

    store = build_token_store(Settings(token_secret=SECRET, dev_mode=True))
    token = store.create_session("default").token

    with pytest.raises(UnknownSession):
        make_store().verify_and_consume_token(token)
