# Ocurate gaze-analysis service

Backend for the Ocurate web interface. Read [CONTEXT.md](./CONTEXT.md) for the domain terms and [architecture-design.md](./architecture-design.md) for the pipeline and the frontend ↔ backend contract.

## Setup

```
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

## Database

Passages are read from MySQL. `compose.yaml` runs one locally, with an `ocurate` database kept in the `mysql-data` volume. Choose the credentials through environment variables (or a `.env` file next to `compose.yaml`, which git ignores). They take effect the first time the volume is created:

```
export MYSQL_USER=ocurate
export MYSQL_PASSWORD=choose-a-password
docker compose up -d --wait
```

If port 3306 is already taken, set `MYSQL_PORT` to another host port and use that port in the URL below.

Point the service at it (the password is percent-encoded so characters like `@` or `/` are safe), then create the `passages` table and bring the default Passage up to date with the code (safe to re-run, also when several processes run it at once):

```
export OCURATE_DATABASE_URL="mysql+pymysql://$MYSQL_USER:$(python3 -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["MYSQL_PASSWORD"], safe=""))')@127.0.0.1:${MYSQL_PORT:-3306}/ocurate?charset=utf8mb4"
venv/bin/python passage_store.py
```

Stop the container with `docker compose down`; the data stays in the volume. `docker compose down -v` also deletes it.

The tests mock the database connection and need no MySQL server. The `/passages` endpoints answer 503 when the database is unreachable or the table is missing (run the command above), and an invalid stored row is left out of the listing and answers 500 on its own id.

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
| `OCURATE_DATABASE_URL` | unset | SQLAlchemy URL of the MySQL database holding the Passages; the `/passages` endpoints answer 503 while unset |
| `OCURATE_TOKEN_TTL_SECONDS` | `60` | How long a Session token stays valid |
| `OCURATE_SESSION_INACTIVITY_SECONDS` | `30` | Seconds without frames before a Session is abandoned |
| `OCURATE_MAX_MESSAGE_BYTES` | `65536` | Largest accepted WebSocket message |
| `OCURATE_MAX_FRAMES_PER_SECOND` | `30` | Frame-rate cap per Session |
| `OCURATE_MAX_CONCURRENT_SESSIONS` | `100` | Live Sessions allowed at once |
| `OCURATE_MAX_CALIBRATION_ATTEMPTS` | `3` | Calibration attempts per Session before it is abandoned |
| `OCURATE_LOG_LEVEL` | `INFO` | Python logging level |

Unset secrets let the app start for local development. The endpoints that need them must refuse to work while they are unset.

## Logging

Structured log lines go through `log_setup.log_event`, which drops landmarks, features, tokens and results. Do not log them any other way.
