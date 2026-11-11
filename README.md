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

### When reading shows no progress

Reading starts only when a fixation lands on the first Cell (top left), and until then the service sends nothing, so a stalled Session looks the same whatever the cause. Watch the logs while you read (`docker compose logs -f api`):

- `calibration_judged`: `ok_points` of `points` were usable. A pass needs 12, but a model fitted on 12 is rougher than one fitted on 16.
- `reading_progress`: every 5 s of browser time while reading, and the same counters are on `session_ended`. Counts and one rounded distance only, no gaze coordinates.

| Field | Meaning |
|---|---|
| `frames` | Reading frames the service received. `0` means the browser is not sending any (check the browser console). |
| `no_face_frames` | Frames with no usable face (landmarks missing or off the image). A high share means lighting, head position or the camera. |
| `gaze_off_screen_frames` | Frames whose estimated gaze was outside the viewport. A high share means the gaze model is badly off, usually after a poor calibration. |
| `fixation_frames` | Frames in which the detector saw a steady gaze (it reports one on every frame of a stare). `0` with plenty of `frames` means the gaze never settles (too jittery) or is off screen. |
| `off_cell_frames` | Of those, frames whose fixation was on no Cell. |
| `cells_fixated` | How many times the fixated Cell changed. |
| `cells_fixated_before_start` | The same, before the first Cell was fixated. Above `0` while `reading_started=False` means the gaze settles on other Cells instead of the first one. |
| `nearest_to_first_cell` | How far (0 to 1 of the viewport) the closest fixation got to Cell (0, 0) before reading started. A Cell is about 0.07 wide and 0.15 high, so a value near `0.2` or more means the estimate is far from where the Learner looks. |
| `frames_out_of_range` | Frames in which some feature was more than 3 calibration standard deviations from its calibration mean, so the gaze estimate is an extrapolation. Close to `frames` means the Learner no longer looks or sits as they did in calibration. |
| `max_abs_z` | The largest such distance seen. Around 3 or less is normal; tens or hundreds means a feature that barely moved during calibration has moved. |
| `mean_max_abs_z` | The average, over frames, of each frame's largest distance. |
| `worst_feature_group` | Which part of the feature vector most often had the largest distance: `iris`, `eye_openness` or `eye_centre`: the groups the model uses (head pose and face position are left out, see `MODEL_FEATURE_GROUPS`). `None` if no frame went out of range. `eye_centre` here means the browser's eye-centre estimate is jittery or jumping, for example from glasses reflections or poor lighting. |
| `reading_started` | `True` once the first Cell was fixated. |
