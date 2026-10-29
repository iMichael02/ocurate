# T9: Session creation and tokens

The web server calls `POST /sessions` to start a Session for a Learner. This service answers with a session id and a short-lived token. The web server hands both to the browser, and the browser puts the token in its WebSocket `hello` message (T8). Only the web server can create Sessions, because only it has the API key.

Code: [tokens.py](../app/sessions/tokens.py) (signing, one-time use), [sessions_api.py](../app/api/sessions_api.py) (the endpoint), [schemas/sessions.py](../app/schemas/sessions.py) (request and response).

## Request and response

```
POST /sessions
X-API-Key: <OCURATE_API_KEY>
Content-Type: application/json

{"passage_id": "default"}
```

```
201 Created

{
  "session_id": "Xq3n0d5bWm1Kz7yQ2r8T4A",
  "passage_id": "default",
  "token": "eyJzaWQiOi...In0.8kQ1...",
  "expires_in": 60
}
```

`expires_in` is in seconds, so the web server does not need our clock.

| Status | When | Body |
|---|---|---|
| 201 | Session created | as above |
| 401 | API key missing, wrong or not configured (same answer for all three) | `{"detail": "unauthorized"}` |
| 404 | Passage id not in the database, nothing is created | `{"detail": "unknown passage id"}` |
| 422 | Body is not `{"passage_id": "<non-empty string>"}` | FastAPI validation error |
| 500 | The stored Passage is not a valid Passage | `{"detail": "stored passage is invalid"}` |
| 503 | The token secret is not set (only a caller with the key sees this) | `{"detail": "session creation is not configured"}` |
| 503 | `OCURATE_DATABASE_URL` is not set | `{"detail": "passage database not configured"}` |
| 503 | The Passage database is unreachable | `{"detail": "passage database unavailable"}` |
| 503 | `OCURATE_MAX_CONCURRENT_SESSIONS` Sessions are already waiting for their token | `{"detail": "too many pending sessions"}` |

The API key is checked before anything else, so a caller without the key gets 401 even with a bad body, and learns nothing about how the service is configured. The one exception is a body that is not valid JSON at all: FastAPI rejects it with 422 before any check runs.

## Token flow

1. The web server sends `POST /sessions` with its API key. We compare the key with `hmac.compare_digest`, so the time taken does not leak how much of it matched.
2. We look the Passage id up in the database, make a random session id and token id (`secrets.token_urlsafe`), and store the token id, session id and Passage id as pending until the token expires.
3. The token is `base64url(payload) + "." + base64url(HMAC-SHA256(secret, payload))`. The payload is `{"exp", "jti"}`: expiry (unix seconds, rounded up so the token lives at least `OCURATE_TOKEN_TTL_SECONDS`) and token id. The session id and Passage id are not in the token; they are looked up in the pending entry by token id. The signature means nobody can change the payload without the secret.
4. The browser opens the WebSocket and sends the token. T8 calls `app.state.tokens.verify_and_consume_token(token)`.
5. That function checks the signature (constant-time), then under one lock checks expiry, checks that it was not used, takes it out of pending and marks it used. It returns `(session_id, passage_id)` or raises one of the errors below. A second try, even at the same moment, gets `already_used`.

| Error | `code` | Meaning |
|---|---|---|
| `InvalidSignature` | `invalid_signature` | Changed, badly formed or signed with another secret |
| `TokenExpired` | `expired` | Past its expiry |
| `TokenAlreadyUsed` | `already_used` | Used before |
| `UnknownSession` | `unknown_session` | Signed by us but not pending here, e.g. made before a restart |

All four are `TokenError`, so T8 can catch that one class and close with `4401` (`invalid_token`).

## Config

| Variable | Default | Meaning |
|---|---|---|
| `OCURATE_API_KEY` | unset | Key the web server sends in `X-API-Key`. Unset means every call gets 401. |
| `OCURATE_TOKEN_SECRET` | unset | HMAC secret for tokens. Unset means 503 for a caller with the key, unless dev mode. |
| `OCURATE_TOKEN_TTL_SECONDS` | `60` | Token lifetime. Short on purpose, it only has to cover the time between creating the Session and opening the WebSocket. Must be above 0 or the app will not start. |
| `OCURATE_DATABASE_URL` | unset | SQLAlchemy URL of the MySQL database holding the Passages (see README.md). Unset means 503. |
| `OCURATE_MAX_CONCURRENT_SESSIONS` | `100` | Most Sessions that may wait for their token at once. |
| `OCURATE_DEV_MODE` | `0` | Local dev only. With no token secret, a random one is made at startup and a warning is logged. |

There is no usable default secret. To make one: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

Local test run (PowerShell; in a second window for the request). Set `OCURATE_DATABASE_URL` too (README.md, "Database"), since the Passage is looked up there:

```
$env:OCURATE_API_KEY = "dev-key"; $env:OCURATE_DEV_MODE = "1"; $env:OCURATE_DATABASE_URL = "<url from the README>"
venv\Scripts\uvicorn app.app:app
Invoke-RestMethod -Method Post http://127.0.0.1:8000/sessions -Headers @{"X-API-Key"="dev-key"} -ContentType "application/json" -Body '{"passage_id": "default"}'
```

## Logging

We log `session_created` with the session id and Passage id, `session_create_refused` with a reason (`unauthorized`, `api_key_unset`, `token_secret_unset` or `too_many_pending`), and `passage_database_error` with the error class. The API key, the token and the secret are never logged, and `tests/api/test_sessions_api.py` checks this.

## Known limits

- **Memory only, single process.** Pending and used tokens live in this process's memory. Run one uvicorn worker. With several workers, a token made by one worker is `unknown_session` on another.
- **Lost on restart.** Pending and used tokens are gone after a restart, so their tokens give `unknown_session`, including a token that had already been used (it cannot be replayed, but it is not reported as `already_used`). The web server just creates a new Session.
- **Dev mode secret** changes on every start, so all old tokens become `invalid_signature`. Do not use `--reload` or several workers with `OCURATE_DEV_MODE=1`; each reload or worker gets its own secret and its own token tables.
- Expired entries are removed from the front of an expiry-ordered structure on every create and verify, so the cost per call stays small. Pending Sessions are capped at `OCURATE_MAX_CONCURRENT_SESSIONS`; past that `POST /sessions` answers 503 `too many pending sessions` until some are used or expire.
- The lock is a `threading.Lock`. It is held only for a few dict operations, so calling it from T8's async WebSocket handler is fine.
