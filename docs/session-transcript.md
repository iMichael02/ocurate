# Example Session transcript

One complete Session as seen on the WebSocket, over protocol version 1. It is illustrative: the Passage is two lines of nine Cells, landmark values are made up, and runs of similar `frame` messages are shortened to the first and last of each run. Every message in a `json client` or `json server` block is validated against `protocol.py` by `tests/test_protocol.py`, so this document cannot drift from the schemas. See [websocket-protocol.md](./websocket-protocol.md) for the rules.

Before the socket opens, the web server has called `POST /sessions` and handed the browser a session id and a short-lived token. The browser has fetched the Passage from `GET /passages/{id}` and rendered it.

## 1. Handshake

**browser → service** — first message; version is checked before the token

```json client
{"type":"hello","version":1,"token":"eyJzaWQiOiJhYmMxMjMiLCJleHAiOjE3NjAwMDAwNjB9.c2lnbmF0dXJl"}
```

**service → browser**

```json server
{"type":"hello_ack","version":1,"supported":[1]}
```

If the browser had sent `version: 2`, the service would answer `{"type":"error","code":"unsupported_version","message":"Protocol version 2 is not supported","supported":[1]}` and close the socket with `4409`.

## 2. Layout

**browser → service** — sent once, fixed for the Session

```json client
{"type":"layout","viewport":{"width":1280,"height":720},"cells":[{"row":0,"col":0,"x":0.05,"y":0.2,"w":0.1,"h":0.15},{"row":0,"col":1,"x":0.15,"y":0.2,"w":0.1,"h":0.15},{"row":0,"col":2,"x":0.25,"y":0.2,"w":0.1,"h":0.15},{"row":0,"col":3,"x":0.35,"y":0.2,"w":0.1,"h":0.15},{"row":0,"col":4,"x":0.45,"y":0.2,"w":0.1,"h":0.15},{"row":0,"col":5,"x":0.55,"y":0.2,"w":0.1,"h":0.15},{"row":0,"col":6,"x":0.65,"y":0.2,"w":0.1,"h":0.15},{"row":0,"col":7,"x":0.75,"y":0.2,"w":0.1,"h":0.15},{"row":0,"col":8,"x":0.85,"y":0.2,"w":0.1,"h":0.15},{"row":1,"col":0,"x":0.05,"y":0.35,"w":0.1,"h":0.15},{"row":1,"col":1,"x":0.15,"y":0.35,"w":0.1,"h":0.15},{"row":1,"col":2,"x":0.25,"y":0.35,"w":0.1,"h":0.15},{"row":1,"col":3,"x":0.35,"y":0.35,"w":0.1,"h":0.15},{"row":1,"col":4,"x":0.45,"y":0.35,"w":0.1,"h":0.15},{"row":1,"col":5,"x":0.55,"y":0.35,"w":0.1,"h":0.15},{"row":1,"col":6,"x":0.65,"y":0.35,"w":0.1,"h":0.15},{"row":1,"col":7,"x":0.75,"y":0.35,"w":0.1,"h":0.15},{"row":1,"col":8,"x":0.85,"y":0.35,"w":0.1,"h":0.15}]}
```

## 3. Calibration

The browser shows each of the 16 targets in turn (a 4×4 grid from 0.1 to 0.9) and tags every frame with the current `target`. The service reports per-point status as samples arrive.

**browser → service** — first frame, target 0

```json client
{"type":"frame","t":5000.0,"iris":[{"x":0.62,"y":0.41},{"x":0.63,"y":0.42},{"x":0.62,"y":0.43},{"x":0.61,"y":0.42},{"x":0.38,"y":0.41},{"x":0.39,"y":0.42},{"x":0.38,"y":0.43},{"x":0.37,"y":0.42}],"eye_corners":[{"x":0.66,"y":0.42},{"x":0.58,"y":0.42},{"x":0.62,"y":0.4},{"x":0.62,"y":0.44},{"x":0.42,"y":0.42},{"x":0.34,"y":0.42},{"x":0.38,"y":0.4},{"x":0.38,"y":0.44}],"nose":{"x":0.5,"y":0.55},"matrix":[[0.99,0.01,-0.02,1.2],[-0.01,0.99,0.03,-0.8],[0.02,-0.03,0.99,-35.0],[0,0,0,1]],"target":{"x":0.1,"y":0.1}}
```

**service → browser**

```json server
{"type":"calibration_status","points":[{"index":0,"state":"collecting","samples":4},{"index":1,"state":"pending","samples":0},{"index":2,"state":"pending","samples":0},{"index":3,"state":"pending","samples":0},{"index":4,"state":"pending","samples":0},{"index":5,"state":"pending","samples":0},{"index":6,"state":"pending","samples":0},{"index":7,"state":"pending","samples":0},{"index":8,"state":"pending","samples":0},{"index":9,"state":"pending","samples":0},{"index":10,"state":"pending","samples":0},{"index":11,"state":"pending","samples":0},{"index":12,"state":"pending","samples":0},{"index":13,"state":"pending","samples":0},{"index":14,"state":"pending","samples":0},{"index":15,"state":"pending","samples":0}],"outcome":null,"attempt":1,"max_attempts":3}
```

… about 30 frames per target, 15 more targets …

**browser → service** — last frame, target 15

```json client
{"type":"frame","t":21400.0,"iris":[{"x":0.62,"y":0.41},{"x":0.63,"y":0.42},{"x":0.62,"y":0.43},{"x":0.61,"y":0.42},{"x":0.38,"y":0.41},{"x":0.39,"y":0.42},{"x":0.38,"y":0.43},{"x":0.37,"y":0.42}],"eye_corners":[{"x":0.66,"y":0.42},{"x":0.58,"y":0.42},{"x":0.62,"y":0.4},{"x":0.62,"y":0.44},{"x":0.42,"y":0.42},{"x":0.34,"y":0.42},{"x":0.38,"y":0.4},{"x":0.38,"y":0.44}],"nose":{"x":0.5,"y":0.55},"matrix":[[0.99,0.01,-0.02,1.2],[-0.01,0.99,0.03,-0.8],[0.02,-0.03,0.99,-35.0],[0,0,0,1]],"target":{"x":0.9,"y":0.9}}
```

**service → browser** — calibration succeeded on attempt 1

```json server
{"type":"calibration_status","points":[{"index":0,"state":"ok","samples":30},{"index":1,"state":"ok","samples":30},{"index":2,"state":"ok","samples":30},{"index":3,"state":"ok","samples":30},{"index":4,"state":"ok","samples":30},{"index":5,"state":"ok","samples":30},{"index":6,"state":"ok","samples":30},{"index":7,"state":"ok","samples":30},{"index":8,"state":"ok","samples":30},{"index":9,"state":"ok","samples":30},{"index":10,"state":"ok","samples":30},{"index":11,"state":"ok","samples":30},{"index":12,"state":"ok","samples":30},{"index":13,"state":"ok","samples":30},{"index":14,"state":"ok","samples":30},{"index":15,"state":"ok","samples":30}],"outcome":"ready","attempt":1,"max_attempts":3}
```

**browser → service**

```json client
{"type":"calibration_done"}
```

### If calibration fails

When fewer than 12 points are usable, or a row or column of the grid has none, the service reports a failure and the Session stays in calibration. The browser sends `calibration_restart` and streams the targets again. After `max_attempts` failures the Session ends abandoned.

**service → browser** — attempt 1 of 3 failed

```json server
{"type":"calibration_status","points":[{"index":0,"state":"ok","samples":30},{"index":1,"state":"ok","samples":30},{"index":2,"state":"ok","samples":30},{"index":3,"state":"ok","samples":30},{"index":4,"state":"ok","samples":30},{"index":5,"state":"ok","samples":30},{"index":6,"state":"ok","samples":30},{"index":7,"state":"ok","samples":30},{"index":8,"state":"skipped","samples":0},{"index":9,"state":"skipped","samples":0},{"index":10,"state":"skipped","samples":0},{"index":11,"state":"skipped","samples":0},{"index":12,"state":"skipped","samples":0},{"index":13,"state":"skipped","samples":0},{"index":14,"state":"skipped","samples":0},{"index":15,"state":"skipped","samples":0}],"outcome":"failed","attempt":1,"max_attempts":3,"reason":"too_few_points"}
```

**browser → service**

```json client
{"type":"calibration_restart"}
```

On the last attempt the service would send `{"type":"error","code":"calibration_failed","message":"Calibration failed"}`, then `{"type":"abandoned","reason":"calibration_failed"}`, and close with `1000`.

## 4. Reading

Frames now carry no `target`. The first Fixation on the Passage's first Cell starts the clock.

**browser → service** — no target

```json client
{"type":"frame","t":23000.0,"iris":[{"x":0.62,"y":0.41},{"x":0.63,"y":0.42},{"x":0.62,"y":0.43},{"x":0.61,"y":0.42},{"x":0.38,"y":0.41},{"x":0.39,"y":0.42},{"x":0.38,"y":0.43},{"x":0.37,"y":0.42}],"eye_corners":[{"x":0.66,"y":0.42},{"x":0.58,"y":0.42},{"x":0.62,"y":0.4},{"x":0.62,"y":0.44},{"x":0.42,"y":0.42},{"x":0.34,"y":0.42},{"x":0.38,"y":0.4},{"x":0.38,"y":0.44}],"nose":{"x":0.5,"y":0.55},"matrix":[[0.99,0.01,-0.02,1.2],[-0.01,0.99,0.03,-0.8],[0.02,-0.03,0.99,-35.0],[0,0,0,1]]}
```

**service → browser**

```json server
{"type":"reading_started"}
```

**service → browser** — live highlight

```json server
{"type":"fixation","row":0,"col":0,"t":23400.0}
```

… more frames; one `fixation` message each time the fixated Cell changes …

**service → browser**

```json server
{"type":"fixation","row":0,"col":5,"t":25100.0}
```

**browser → service**

```json client
{"type":"frame","t":25133.0,"iris":[{"x":0.67,"y":0.41},{"x":0.68,"y":0.42},{"x":0.67,"y":0.43},{"x":0.66,"y":0.42},{"x":0.43,"y":0.41},{"x":0.44,"y":0.42},{"x":0.43,"y":0.43},{"x":0.42,"y":0.42}],"eye_corners":[{"x":0.66,"y":0.42},{"x":0.58,"y":0.42},{"x":0.62,"y":0.4},{"x":0.62,"y":0.44},{"x":0.42,"y":0.42},{"x":0.34,"y":0.42},{"x":0.38,"y":0.4},{"x":0.38,"y":0.44}],"nose":{"x":0.5,"y":0.55},"matrix":[[0.99,0.01,-0.02,1.2],[-0.01,0.99,0.03,-0.8],[0.02,-0.03,0.99,-35.0],[0,0,0,1]]}
```

… the Learner reads on to the second line …

## 5. Completion

The first Fixation on the last Cell (row 1, column 8) ends the reading.

**service → browser**

```json server
{"type":"fixation","row":1,"col":8,"t":33400.0}
```

**service → browser** — the same result is sent to the web server through the signed callback

```json server
{"type":"completed","result":{"elapsed_seconds":10.0,"cpm":108.0,"wpm":18.0,"saccades":17,"regressions":1,"skipped_characters":0,"sequence":[{"row":0,"col":0},{"row":0,"col":1},{"row":0,"col":2},{"row":0,"col":3},{"row":0,"col":5},{"row":0,"col":4},{"row":0,"col":6},{"row":0,"col":7},{"row":0,"col":8},{"row":1,"col":0},{"row":1,"col":1},{"row":1,"col":2},{"row":1,"col":3},{"row":1,"col":4},{"row":1,"col":5},{"row":1,"col":6},{"row":1,"col":7},{"row":1,"col":8}]}}
```

`elapsed_seconds` is the difference between the browser timestamps of the first and last Fixation (here 33400 − 23400 ms). After `completed` the service closes the socket with `1000`.

## Abandonment

At any point a `quit`, a `viewport_changed`, a socket drop or 30 s without frames ends the Session. If the socket is still open, the service sends, for example, `{"type":"abandoned","reason":"viewport_changed"}`. No result is produced, and the Learner must start a new Session.
