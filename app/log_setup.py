import logging

# The service must hold no biometric data (see docs/adr/0003): these fields
# are dropped from every structured log line, whatever the caller passes.
SENSITIVE_FIELDS = frozenset({
    "token",
    "api_key",
    "secret",
    "signature",
    "landmarks",
    "matrix",
    "features",
    "frame",
    "result",
    "sequence",
})


def format_event(event, **fields):
    """Renders one structured log line, e.g. `session_ended session_id=abc reason=quit`."""

    parts = [event]

    for key, value in fields.items():
        if key in SENSITIVE_FIELDS:
            continue
        parts.append(f"{key}={value}")

    return " ".join(parts)


def log_event(logger, event, level=logging.INFO, **fields):

    logger.log(level, format_event(event, **fields))


def configure_logging(level="INFO"):

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
