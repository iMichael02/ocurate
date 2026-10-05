# WebSocket protocol (draft, T2)

Status: **design only, not implemented.** This is the proposed single definition of every message exchanged between the browser and this service. Schemas, tests and the example transcript will all be derived from it. Context and lifecycle: [architecture-design.md](../architecture-design.md) section 0.

Scope: the browser ↔ service WebSocket only. `POST /sessions` and the signed result callback (web server ↔ service) are separate HTTP contracts and are out of scope.

## Who uses this

- **Service**: validates every incoming message and builds every outgoing one from the schemas.
- **Frontend**: codes against the same shapes, the transcript and the reason codes.
- **Tests**: use the schemas as the source of truth.

## Conventions

- JSON text frames. Every message is an object with a `type` field.
- Schemas are Pydantic models with `extra="forbid"` and `allow_inf_nan=False`. Unknown `type`, missing fields, extra fields, wrong types and non-finite numbers are rejected.
- Coordinates are normalized to 0–1 unless stated otherwise.
- All timing uses the browser's `t` (ms), never arrival time. `t` must not go backwards.
- Validation errors name the field path but never echo values (landmarks, tokens).

## Version handshake

- The service supports a set of versions, initially `{1}`.
- `hello` is the first message and carries `version` and `token`.
- The version is checked before the token. If supported, the service replies `hello_ack`. Otherwise it sends `error{code: "unsupported_version", supported: [...]}` and closes with `4409`.

## Browser → service

| `type` | Fields |
|---|---|
| `hello` | `version` (int), `token` (string) |
| `layout` | `viewport`: `{width, height}` (px, > 0). `cells`: list of `{row, col, x, y, w, h}`, rectangle in 0–1 (viewport-normalized), `w` and `h` > 0, inside the viewport. Must cover every Cell of the Passage with no duplicate (row, col). Sent once, before calibration. |
| `frame` | `t` (ms, finite). `iris`: 8 × `{x, y}`. `eye_corners`: 8 × `{x, y}`. `nose`: `{x, y}`. `matrix`: 4 × 4 numbers (4 rows of 4). `target`: optional `{x, y}`, present only during calibration. |
| `calibration_restart` | none. Only valid after a `failed` outcome with attempts left. Discards the failed attempt's samples. |
| `calibration_done` | none |
| `viewport_changed` | none |
| `quit` | none |

`frame` landmark order is fixed and mirrors `eye_features.py`:

- `iris`: left eye 474, 475, 476, 477, then right eye 469, 470, 471, 472.
- `eye_corners`: left eye (362 left, 263 right, 386 top, 374 bottom), then right eye (133 left, 33 right, 159 top, 145 bottom).
- `nose`: nose tip.

Landmark `x` and `y` are MediaPipe's values, normalized to the camera image (not the viewport), and are sent unchanged. They can fall slightly outside 0–1 when the face is partly out of frame, so the accepted range is **−0.5 to 1.5**. Values outside it are rejected (`invalid_message`). Values inside the margin but outside 0–1 are valid input; the feature code treats such frames as unusable rather than the protocol rejecting them. `target` and `layout` coordinates are viewport-normalized and must be strictly within 0–1. `z` is not sent (the current features do not use it).

`matrix` convention: 4 rows of 4 numbers, **row-major**, as `eye_features.py` reads it (rotation in `[:3, :3]`, translation in `[:3, 3]`). MediaPipe's `facialTransformationMatrixes[0]` is a flat 16-value array that, as far as we recall, is column-major, so the browser must transpose while reshaping. Verify against real MediaPipe output when the frontend is built, and correct this note if it is wrong.

Relation to MediaPipe: `frame` is a reduced copy of the Face Landmarker result (17 of 478 landmarks, no `z`, no blendshapes), plus `t` and the optional `target`.

## Service → browser

| `type` | Fields |
|---|---|
| `hello_ack` | `version` (negotiated), `supported` (list of ints) |
| `calibration_status` | `points`: 16 × `{index, state, samples}` where `state` is `pending`, `collecting`, `ok` or `skipped`. `outcome`: `null`, `ready` or `failed`. `reason` when failed. `attempt` and `max_attempts` (ints). |
| `reading_started` | none |
| `fixation` | `row`, `col`, `t` |
| `completed` | `result`: `{cpm, wpm, elapsed_s, saccades, regressions, skipped_chars}`. `fixations`: list of `{row, col, t, duration}`. |
| `abandoned` | `reason` |
| `error` | `code`, `message` (human-readable only) |

`hello_ack` is new relative to architecture-design.md section 0; add it there when this is implemented.

## Errors and close reasons

`error.code`:

- `unsupported_version`
- `invalid_token`
- `invalid_message` (schema failure)
- `out_of_order` (message not allowed in the current state)
- `timestamp_regression`
- `calibration_failed` (sent with the final failed attempt, together with `abandoned`)

`abandoned.reason`:

- `socket_closed`
- `quit`
- `viewport_changed`
- `frame_timeout` (30 s without frames)
- `protocol_error`
- `calibration_failed` (all attempts used)

WebSocket close codes:

| Code | Meaning |
|---|---|
| `1000` | normal completion, or abandoned after calibration attempts are exhausted |
| `4400` | invalid message |
| `4401` | bad token |
| `4408` | timeout |
| `4409` | unsupported version |

## State order

```
hello → hello_ack
layout
frame (with target) … → calibration_status … → ready
   (on failed: calibration_restart, up to max_attempts, then abandoned)
calibration_done
frame (no target) … → reading_started → fixation … → completed
```

## Calibration retries

A failed calibration is retried on the same socket, up to `max_attempts` attempts in total (default 3, configurable via `OCURATE_*` settings). This is not a resume: the Layout, token and Session are unchanged, only the calibration samples are discarded.

- On failure, the service sends `calibration_status{outcome: "failed", attempt, max_attempts}`. If `attempt < max_attempts`, the Session stays in the calibration state and the browser sends `calibration_restart`, then streams `frame`s with `target` again from the first point.
- If `attempt == max_attempts`, the service sends `error{code: "calibration_failed"}` and `abandoned{reason: "calibration_failed"}`, then closes with `1000`. The Learner must start a new Session.
- The 30 s frame timeout still applies during retries.
- Samples from failed attempts are never kept.

`viewport_changed`, `quit`, a socket drop or `frame_timeout` end the Session as `abandoned` at any point. A message that arrives in the wrong state gets `out_of_order`.

## Open points

- The default for `max_attempts` (3) is a proposal.
- The example transcript (handshake, layout, calibration, reading, completion) is produced at implementation time.
- Acceptance tests: one valid and one invalid example per message type, plus out-of-range landmarks, a non-4×4 matrix, non-finite numbers, and the −0.5/1.5 landmark boundaries.
