# Result callback (T10, proposal)

Status: **proposed, not implemented.** This is the contract between this service and the web server for reporting a completed Session. Decided in review: a restart may drop pending results, retries last 15 minutes, and abandoned Sessions are not reported. The signature scheme is the [Standard Webhooks](https://www.standardwebhooks.com) specification, because the web server has no convention of its own and ready-made verification libraries exist for most languages. Context: [ADR 0003](./adr/0003-split-web-interface-and-gaze-service.md) (the browser never relays results) and [architecture-design.md](../architecture-design.md) section 0, steps 5 and 6.

Scope: service → web server only. The browser WebSocket is in [websocket-protocol.md](./websocket-protocol.md) and `POST /sessions` in [t9-sessions.md](./t9-sessions.md).

## When it is sent

Once per Session, only when it ends `completed`: the Learner reached the last Cell and the body carries the result.

Abandoned Sessions (`quit`, `viewport_changed`, `frame_timeout`, `socket_closed`, `protocol_error`, `calibration_failed`) send nothing, and neither does a connection refused during the handshake. The web server learns that a Session was abandoned only by never receiving a result for its `session_id`.

The service sends it from `app.state.on_session_finished(outcome)`, with the `Outcome` the Session manager already builds. It does not wait for the callback before closing the WebSocket, so a slow web server never holds a Learner's socket open.

## Request

```
POST <OCURATE_CALLBACK_URL>
Content-Type: application/json
webhook-id: Xq3n0d5bWm1Kz7yQ2r8T4A
webhook-timestamp: 1760000123
webhook-signature: v1,K5oZfzN95Z9UVu1EsfQmfVNQhnkZ2/d+B4jv4/HmUDY=
```

Body:

```json
{
  "session_id": "Xq3n0d5bWm1Kz7yQ2r8T4A",
  "passage_id": "default",
  "status": "completed",
  "result": {
    "elapsed_seconds": 10.0,
    "cpm": 108.0,
    "wpm": 18.0,
    "saccades": 17,
    "regressions": 1,
    "skipped_characters": 0,
    "sequence": [{"row": 0, "col": 0}, {"row": 0, "col": 1}]
  }
}
```

- `session_id` is the id returned by `POST /sessions`. It is the only identity the service knows: it never sees the Learner, so the web server maps the id back to the Learner it created the Session for.
- `result` is exactly what the `completed` WebSocket message carries (`schemas/protocol.Result`), so what the Learner sees and what the web server stores are the same numbers.
- The body holds no token, landmark, feature, calibration sample or timestamp from the browser, only the summary and the Cell sequence the web server is meant to store (ADR 0003).

## Signature (Standard Webhooks)

- `webhook-id` is the `session_id`. It is the same on every retry, so the web server uses it as the idempotency key.
- `webhook-timestamp` is the time of this attempt in unix seconds.
- `webhook-signature` is `v1,` followed by the base64 of `HMAC-SHA256(key, webhook-id + "." + webhook-timestamp + "." + raw_body)`, where `raw_body` is the exact bytes sent. (The specification allows several space-separated signatures, for secret rotation; this service sends one.)
- `OCURATE_CALLBACK_SECRET` has the form `whsec_` followed by base64 of at least 24 random bytes (`python -c "import base64, secrets; print('whsec_' + base64.b64encode(secrets.token_bytes(32)).decode())"`). The HMAC key is the decoded bytes. The web server is configured with the same string.

The web server should use a Standard Webhooks library to verify, or do the same by hand:

1. Recompute the HMAC over the raw bytes it received (before parsing JSON) and compare in constant time.
2. Reject a `webhook-timestamp` more than 5 minutes from its own clock, so a captured request cannot be replayed later.
3. Store the first result per `webhook-id` and answer `200` to repeats (below).

## Response and retries

| Web server answers | Service does |
|---|---|
| `2xx` | Acknowledged. Done. A repeat of an already-stored `session_id` should also answer `200`. |
| `408`, `429`, `5xx`, or no answer (timeout, connection error) | Retry. |
| any other `4xx` | Give up and log it (`callback_rejected` with the status). Retrying a rejected request would not change the answer. |

- **Idempotency:** retries send the same body for the same `session_id`; only the timestamp and signature change. The web server stores the first result it accepts for a `session_id` and answers `200` to repeats without changing it.
- **Backoff:** 1 s, 2 s, 4 s, ... doubling up to 60 s, with up to 20% random jitter, for at most 15 minutes from the first attempt. After that the service logs `callback_dropped` and drops it.
- **Per-attempt timeout:** 5 s.
- **Redirects** are not followed.
- **Transport:** `OCURATE_CALLBACK_URL` must be `https://`. `http://` is accepted only for `localhost` / `127.0.0.1`, for local development.

## Configuration

| Variable | Meaning |
|---|---|
| `OCURATE_CALLBACK_URL` | Where to POST. Unset means no callbacks. |
| `OCURATE_CALLBACK_SECRET` | `whsec_…` signing secret shared with the web server (see Signature). Rotating it means updating both sides. |

If either is unset the callback is switched off: the service logs a warning at startup, Sessions still run, and results only reach the Learner's browser. If the URL is set but the secret is missing or not in the `whsec_` form, the app refuses to start rather than send unsigned results.

## Logging

`callback_sent` / `callback_retry` / `callback_rejected` / `callback_dropped`, with the session id, attempt number and HTTP status. The secret, signature and body are never logged.

## Known limits (follow from "the service persists nothing")

- **The retry queue lives in memory.** If the service restarts while a callback is waiting to be retried, that result is dropped (accepted in review). The Learner still saw it on screen, but the web server never stores it, and it sees the same silence as for an abandoned Session.
- The queue is capped (1000 pending callbacks); past that the oldest is dropped with a `callback_dropped` log.

## Decisions from review

1. Pending results are dropped on restart. Accepted.
2. Retry window: 15 minutes.
3. Abandoned Sessions are not reported.

## Implementation plan (after review)

1. `callback.py`: build the body from an `Outcome`, sign it as above, send it with `httpx`.
2. A background sender with the retry schedule and queue cap, started and stopped with the app's lifespan.
3. Config validation (URL scheme, secret required with URL) and wiring into `app.state.on_session_finished`.
4. Tests with a mocked HTTP client and a fake clock: signature, each response class, backoff, queue cap, no secret in logs.
