# Ocurate gaze-analysis service

Backend for the Ocurate web interface. Read [CONTEXT.md](./CONTEXT.md) for the domain terms and [architecture-design.md](./architecture-design.md) for the pipeline and the frontend ↔ backend contract.

## Setup

```
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

## Run

```
venv/bin/uvicorn app:app --reload
```

`GET /health` answers `{"status": "ok"}`.

## Test

```
venv/bin/pytest
```

## Configuration

All settings are environment variables. Unset or empty values use the default.

| Variable | Default | Meaning |
|---|---|---|
| `OCURATE_API_KEY` | unset | Key the web server presents when creating Sessions |
| `OCURATE_TOKEN_SECRET` | unset | Secret used to sign Session tokens |
| `OCURATE_CALLBACK_URL` | unset | Web-server URL that receives results |
| `OCURATE_CALLBACK_SECRET` | unset | Shared secret that signs result callbacks |
| `OCURATE_TOKEN_TTL_SECONDS` | `60` | How long a Session token stays valid |
| `OCURATE_SESSION_INACTIVITY_SECONDS` | `30` | Seconds without frames before a Session is abandoned |
| `OCURATE_MAX_MESSAGE_BYTES` | `65536` | Largest accepted WebSocket message |
| `OCURATE_MAX_FRAMES_PER_SECOND` | `30` | Frame-rate cap per Session |
| `OCURATE_MAX_CONCURRENT_SESSIONS` | `100` | Live Sessions allowed at once |
| `OCURATE_LOG_LEVEL` | `INFO` | Python logging level |

Unset secrets let the app start for local development. The endpoints that need them must refuse to work while they are unset.

## Logging

Structured log lines go through `log_setup.log_event`, which drops landmarks, features, tokens and results. Do not log them any other way.
