import os
from dataclasses import dataclass
from typing import Optional

ENV_PREFIX = "OCURATE_"


@dataclass(frozen=True)
class Settings:
    """Service configuration, read from OCURATE_* environment variables.

    Secrets default to None so the app can start for local development;
    the endpoints that need them must refuse to work when they are unset.
    """

    api_key: Optional[str] = None
    token_secret: Optional[str] = None
    callback_url: Optional[str] = None
    callback_secret: Optional[str] = None

    token_ttl_seconds: int = 60
    session_inactivity_seconds: float = 30.0
    max_message_bytes: int = 65536
    max_frames_per_second: int = 30
    max_concurrent_sessions: int = 100
    max_calibration_attempts: int = 3

    log_level: str = "INFO"


def _read(name, cast, default):

    raw = os.environ.get(ENV_PREFIX + name)

    if raw is None or raw == "":
        return default

    try:
        return cast(raw)
    except ValueError:
        raise ValueError(f"{ENV_PREFIX}{name} must be a valid {cast.__name__}, got {raw!r}")


def load_settings():

    defaults = Settings()

    return Settings(
        api_key=_read("API_KEY", str, defaults.api_key),
        token_secret=_read("TOKEN_SECRET", str, defaults.token_secret),
        callback_url=_read("CALLBACK_URL", str, defaults.callback_url),
        callback_secret=_read("CALLBACK_SECRET", str, defaults.callback_secret),
        token_ttl_seconds=_read("TOKEN_TTL_SECONDS", int, defaults.token_ttl_seconds),
        session_inactivity_seconds=_read("SESSION_INACTIVITY_SECONDS", float, defaults.session_inactivity_seconds),
        max_message_bytes=_read("MAX_MESSAGE_BYTES", int, defaults.max_message_bytes),
        max_frames_per_second=_read("MAX_FRAMES_PER_SECOND", int, defaults.max_frames_per_second),
        max_concurrent_sessions=_read("MAX_CONCURRENT_SESSIONS", int, defaults.max_concurrent_sessions),
        max_calibration_attempts=_read("MAX_CALIBRATION_ATTEMPTS", int, defaults.max_calibration_attempts),
        log_level=_read("LOG_LEVEL", str, defaults.log_level).upper(),
    )
