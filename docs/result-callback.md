# Result callback (T10, proposal)

Status: **proposed, not implemented.** This is the contract between this service and the web server for reporting how a Session ended. It is open for review; the open questions at the end need an answer before the code is written. Context: [ADR 0003](./adr/0003-split-web-interface-and-gaze-service.md) (the browser never relays results) and [architecture-design.md](../architecture-design.md) section 0, steps 5 and 6.

Scope: service → web server only. The browser WebSocket is in [websocket-protocol.md](./websocket-protocol.md) and `POST /sessions` in [t9-sessions.md](./t9-sessions.md).

## When it is sent

Once per Session, when the Session ends:

- `completed`: the Learner reached the last Cell. The body carries the result.
- `abandoned`: any other end (`quit`, `viewport_changed`, `frame_timeout`, `socket_closed`, `protocol_error`, `calibration_failed`). The body carries only the reason; abandoned Sessions are not scored.

A connection that is refused during the handshake (bad version, bad token) never became a Session and sends nothing.

The service sends it from `app.state.on_session_finished(outcome)`, with the `Outcome` the Session manager already builds. It does not wait for the callback before closing the WebSocket, so a slow web server never holds a Learner's socket open.

## Request

```
POST <OCURATE_CALLBACK_URL>
Content-Type: application/json
X-Ocurate-Timestamp: 1760000123
X-Ocurate-Signature: sha256=3b1f...
```

Body for a completed Session:

```json
{
  "session_id": "Xq3n0d5bWm1Kz7yQ2r8T4A",
  "passage_id": "default",
  "status": "completed",
  "reason": null,
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

Body for an abandoned Session: the same fields with `"status": "abandoned"`, `"reason": "<abandon reason>"` and `"result": null`.

- `session_id` is the id returned by `POST /sessions`. It is the only identity the service knows: it never sees the Learner, so the web server maps the id back to the Learner it created the Session for.
- `result` is exactly what the `completed` WebSocket message carries (`schemas/protocol.Result`), so what the Learner sees and what the web server stores are the same numbers.
- The body holds no token, landmark, feature, calibration sample or timestamp from the browser, only the summary and the Cell sequence the web server is meant to store (ADR 0003).

## Signature

`X-Ocurate-Signature` is `sha256=` followed by the lowercase hex of `HMAC-SHA256(OCURATE_CALLBACK_SECRET, timestamp + "." + raw_body)`, where `timestamp` is the `X-Ocurate-Timestamp` value (unix seconds, as text) and `raw_body` is the exact bytes sent.

The web server must:

1. Recompute the HMAC over the raw bytes it received (before any JSON parsing) and compare in constant time.
2. Reject a timestamp more than 5 minutes from its own clock, so a captured request cannot be replayed later.
3. Treat `session_id` as the idempotency key (below).

## Response and retries

| Web server answers | Service does |
|---|---|
| `2xx` | Acknowledged. Done. A repeat of an already-stored `session_id` should also answer `200`. |
| `408`, `429`, `5xx`, or no answer (timeout, connection error) | Retry. |
| any other `4xx` | Give up and log it (`callback_rejected` with the status). Retrying a rejected request would not change the answer. |

- **Idempotency:** retries send the same body for the same `session_id`; only the timestamp and signature change. The web server stores the first result it accepts for a `session_id` and answers `200` to repeats without changing it.
- **Backoff:** 1 s, 2 s, 4 s, ... doubling up to 60 s, with up to 20% random jitter, for at most 1 hour from the first attempt. After that the service logs `callback_abandoned` and drops it.
- **Per-attempt timeout:** 5 s.
- **Redirects** are not followed.
- **Transport:** `OCURATE_CALLBACK_URL` must be `https://`. `http://` is accepted only for `localhost` / `127.0.0.1`, for local development.

## Configuration

| Variable | Meaning |
|---|---|
| `OCURATE_CALLBACK_URL` | Where to POST. Unset means no callbacks. |
| `OCURATE_CALLBACK_SECRET` | HMAC secret shared with the web server. |

If either is unset the callback is switched off: the service logs a warning at startup, Sessions still run, and results only reach the Learner's browser. If the URL is set but the secret is not, the app refuses to start rather than send unsigned results.

## Logging

`callback_sent` / `callback_retry` / `callback_rejected` / `callback_abandoned`, with the session id, attempt number and HTTP status. The secret, signature and body are never logged.

## Known limits (follow from "the service persists nothing")

- **The retry queue lives in memory.** If the service restarts while a callback is waiting to be retried, that result is lost. The Learner still saw it on screen, but the web server never stores it.
- The queue is capped (1000 pending callbacks); past that the oldest is dropped with a `callback_abandoned` log.

## Open questions for review

1. **Lost results on restart.** Is that acceptable, or must a result survive a restart? Surviving means an outbox on disk or in a database, which reverses "this service persists nothing". Recommendation: accept the limit for now; a web server that needs certainty can treat a Session with no result after N minutes as unknown.
2. **Header names and signature format.** `X-Ocurate-Timestamp` and `X-Ocurate-Signature: sha256=<hex>`, modelled on common webhook schemes. Does the web server framework already expect something else?
3. **Retry window.** 1 hour is a guess. Does the web server have a deadline after which it would rather not receive a result?
4. **Abandoned Sessions.** Does the web server want them at all? The architecture says the callback reports `abandoned`; this proposal does so, with the reason.
5. **One URL or one per event.** One URL receiving both statuses, as above.

## Implementation plan (after review)

1. `callback.py`: build the body from an `Outcome`, sign it, send it with `httpx`.
2. A background sender with the retry schedule and queue cap, started and stopped with the app's lifespan.
3. Config validation (URL scheme, secret required with URL) and wiring into `app.state.on_session_finished`.
4. Tests with a mocked HTTP client and a fake clock: signature, each response class, backoff, queue cap, no secret in logs.
