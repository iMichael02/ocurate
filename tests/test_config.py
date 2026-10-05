import pytest

from config import load_settings


def test_defaults_when_environment_is_empty(monkeypatch):

    for name in ("API_KEY", "TOKEN_SECRET", "CALLBACK_URL", "CALLBACK_SECRET",
                 "TOKEN_TTL_SECONDS", "SESSION_INACTIVITY_SECONDS", "MAX_MESSAGE_BYTES",
                 "MAX_FRAMES_PER_SECOND", "MAX_CONCURRENT_SESSIONS", "MAX_CALIBRATION_ATTEMPTS", "LOG_LEVEL"):
        monkeypatch.delenv("OCURATE_" + name, raising=False)

    settings = load_settings()

    assert settings.api_key is None
    assert settings.token_secret is None
    assert settings.callback_url is None
    assert settings.callback_secret is None
    assert settings.token_ttl_seconds == 60
    assert settings.session_inactivity_seconds == 30.0
    assert settings.max_message_bytes == 65536
    assert settings.max_frames_per_second == 30
    assert settings.max_concurrent_sessions == 100
    assert settings.max_calibration_attempts == 3
    assert settings.log_level == "INFO"


def test_reads_values_from_environment(monkeypatch):

    monkeypatch.setenv("OCURATE_API_KEY", "key")
    monkeypatch.setenv("OCURATE_TOKEN_TTL_SECONDS", "15")
    monkeypatch.setenv("OCURATE_SESSION_INACTIVITY_SECONDS", "2.5")
    monkeypatch.setenv("OCURATE_LOG_LEVEL", "debug")

    settings = load_settings()

    assert settings.api_key == "key"
    assert settings.token_ttl_seconds == 15
    assert settings.session_inactivity_seconds == 2.5
    assert settings.log_level == "DEBUG"


def test_empty_value_falls_back_to_default(monkeypatch):

    monkeypatch.setenv("OCURATE_MAX_MESSAGE_BYTES", "")

    assert load_settings().max_message_bytes == 65536


def test_invalid_number_names_the_variable(monkeypatch):

    monkeypatch.setenv("OCURATE_MAX_FRAMES_PER_SECOND", "fast")

    with pytest.raises(ValueError, match="OCURATE_MAX_FRAMES_PER_SECOND"):
        load_settings()
