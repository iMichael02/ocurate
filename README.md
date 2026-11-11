# Ocurate gaze-analysis service

Backend for the Ocurate web interface. Read [CONTEXT.md](./CONTEXT.md) for the domain terms and [docs/architecture-design.md](./docs/architecture-design.md) for the pipeline and the frontend ↔ backend contract.

## Prerequisites

- Python 3.12
- Docker with Compose v2 (`docker compose`), for MySQL and for the Docker route

The service needs MySQL for anything beyond `GET /health`: `POST /sessions` and `/ws` both look up a Passage. Both quickstarts below start one in Docker.

## Configure

Both quickstarts read their settings from a `.env` file next to `compose.yaml`. Git ignores it.

```
cp -n .env.example .env
```

`-n` leaves an existing `.env` untouched, so merge any missing keys by hand. The defaults in `.env.example` work for local development. Edit the values if port 3306 or 8000 is taken, or if you change the password (then also update `MYSQL_PASSWORD_URLENCODED` and `OCURATE_DATABASE_URL`).

## Quickstart: Python

Run the service from a venv and keep only MySQL in Docker.

```
python3 -m venv venv
venv/bin/pip install -r requirements.txt

set -a; . ./.env; set +a            # load .env into this shell
docker compose up -d --wait mysql
venv/bin/python -m app.passages.passage_store      # creates the passages table and seeds the Passages
venv/bin/uvicorn app.app:app --reload
```

`OCURATE_DEV_MODE=1` makes the service generate its token secret at startup. The secret and the pending tokens live in one process, so run uvicorn without `--reload` while it is set, or tokens die on every reload.

Check it, from another terminal in the same directory:

```
curl http://localhost:8000/health
# {"status":"ok"}

curl http://localhost:8000/passages
# [{"id":"default", ...}]

curl -X POST http://localhost:8000/sessions \
  -H "X-API-Key: dev-api-key" -H "Content-Type: application/json" \
  -d '{"passage_id": "default"}'
# 201 with session_id, token and expires_in
```

The token is valid for 60 seconds and works once. The frontend dev page on `:5173` opens `/ws` with it; the origin must be listed in `OCURATE_ALLOWED_ORIGINS`.

## Quickstart: Docker

Run the service and MySQL together.

```
docker compose up -d --build --wait
curl http://localhost:8000/health
curl http://localhost:8000/passages
```

A one-shot `migrate` container runs `python -m app.passages.passage_store` once MySQL is healthy, and the `api` container starts only after it exits successfully, so there is no manual migration step. Compose reads `.env` on its own. The `api` container receives only `OCURATE_API_KEY`, `OCURATE_TOKEN_SECRET`, `OCURATE_CALLBACK_*`, `OCURATE_ALLOWED_ORIGINS` and `OCURATE_DEV_MODE`, plus a database URL that Compose builds from the `MYSQL_*` values. To change another setting, add it under `environment:` in `compose.yaml`.

The container runs a single uvicorn process, as pending tokens live in memory. The image holds only `app/` and does not reload, so after a code change run `docker compose up -d --build api`. Tests run from the venv, not the container. For day-to-day development the Python route is faster.

## Database

Passages are read from MySQL. `compose.yaml` runs one, with an `ocurate` database kept in the `mysql-data` volume. `MYSQL_USER` and `MYSQL_PASSWORD` only take effect the first time that volume is created.

`MYSQL_PASSWORD_URLENCODED` must be the percent-encoded form of `MYSQL_PASSWORD`, because it goes into a URL. To produce it:

```
python3 -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["MYSQL_PASSWORD"], safe=""))'
```

`python -m app.passages.passage_store` creates the `passages` table and seeds it. Docker runs it for you through the `migrate` service; from the venv, run it yourself. It waits up to a minute for MySQL to accept connections. It is safe to re-run, also when several processes run it at once.

Seeded Passages (`SEED_PASSAGES` in `app/passages/passage_store.py`); each run makes these rows match the text in code, and leaves any other row alone:

| id | text |
|---|---|
| `default` | three rows: "read the texts", "with your eyes", "and count them" |
| `short` | one row: "i can read this" |

To add a seed, write a builder next to `build_short_passage` in `app/passages/passage.py` and list it in `SEED_PASSAGES`.

Stop the container with `docker compose down`; the data stays in the volume. `docker compose down -v` also deletes it.

The tests mock the database connection and need no MySQL server. The `/passages` endpoints answer 503 when the database is unreachable or the table is missing (run `docker compose up -d --wait`, or the command above from the venv), and an invalid stored row is left out of the listing and answers 500 on its own id.

## Test

```
venv/bin/pytest
```

## Git hooks

[pre-commit](https://pre-commit.com) runs `ruff` and the unit tests before each commit, and rejects commit messages with a line
over 120 characters. Install it once, with the venv active:

```
venv/bin/pip install pre-commit
venv/bin/pre-commit install
```

Run the checks by hand with `pre-commit run --all-files`. CI runs the same tests on every push.

## Configuration

All settings are environment variables. Unset or empty values use the default.

| Variable | Default | Meaning |
|---|---|---|
| `OCURATE_API_KEY` | unset | Key the web server presents when creating Sessions |
| `OCURATE_TOKEN_SECRET` | unset | Secret used to sign Session tokens |
| `OCURATE_CALLBACK_URL` | unset | Web-server URL that receives results; `https://` required (`http://` only for localhost / 127.0.0.1). Unset disables callbacks |
| `OCURATE_CALLBACK_SECRET` | unset | `whsec_<base64>` secret (at least 24 decoded bytes) that signs result callbacks; required when the URL is set, or the app refuses to start |
| `OCURATE_DATABASE_URL` | unset | SQLAlchemy URL of the MySQL database holding the Passages; the `/passages` endpoints answer 503 while unset |
| `OCURATE_TOKEN_TTL_SECONDS` | `60` | How long a Session token stays valid |
| `OCURATE_SESSION_INACTIVITY_SECONDS` | `30` | Seconds without frames before a Session is abandoned |
| `OCURATE_MAX_MESSAGE_BYTES` | `65536` | Largest accepted WebSocket message |
| `OCURATE_MAX_FRAMES_PER_SECOND` | `30` | Frame-rate cap per Session. Frames are paced with a two-second burst allowance, so a browser at 30 fps never trips it; a sustained higher rate ends the Session with `4429` |
| `OCURATE_MAX_CONCURRENT_SESSIONS` | `100` | Sessions allowed to wait for their token at once (`POST /sessions` answers 503 past it), and also the most live WebSockets (an extra one is closed with `1013`) |
| `OCURATE_ALLOWED_ORIGINS` | empty | Comma-separated browser origins (e.g. `http://localhost:5173`) allowed to open `/ws` and to call `GET /passages` (CORS). Empty refuses every browser origin on `/ws` and sends no CORS headers. Clients sending no `Origin` are not checked |
| `OCURATE_MAX_CALIBRATION_ATTEMPTS` | `3` | Calibration attempts per Session before it is abandoned |
| `OCURATE_LOG_LEVEL` | `INFO` | Python logging level |
| `OCURATE_DEV_MODE` | `0` | Local dev only. With no token secret set, a random one is made at startup (tokens then die with the process) |

Unset secrets let the app start for local development. The endpoints that need them must refuse to work while they are unset. Never set `OCURATE_DEV_MODE` in production.

`POST /sessions` needs `OCURATE_API_KEY` and `OCURATE_TOKEN_SECRET` (or `OCURATE_DEV_MODE=1` locally). See [docs/t9-sessions.md](./docs/t9-sessions.md). The WebSocket messages are defined in [docs/websocket-protocol.md](./docs/websocket-protocol.md).

## Logging

Structured log lines go through `log_setup.log_event`, which drops landmarks, features, tokens and results. Do not log them any other way.
