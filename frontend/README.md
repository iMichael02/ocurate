# Ocurate frontend

Plain HTML + CSS + JavaScript (ES modules, no build step) for the Ocurate Braille reading test.
It follows the browser ↔ service contract in `../docs/websocket-protocol.md`.

## Run it

ES modules don't load from `file://`, so serve the folder:

```
cd frontend
python3 -m http.server 5500
```

Open http://localhost:5500 in Chrome or Firefox, click **Enable camera**, then **Start reading test**.

## Mock mode (default)

The backend's WebSocket endpoint isn't written yet, so `js/mock-service.js` plays the service:
same messages, same order, same calibration rules (12 of 16 points, every row and column).
It can't estimate gaze, so **during reading the mouse pointer is the gaze**: hover over each
Cell from the top-left one to the last one.

Switch modes in `js/config.js` (`useMock`) or with the URL: `?mock=0` / `?mock=1`.

## Real service mode (`?mock=0`)

Needs the backend to have `/ws`, `GET /passages/{id}` and `POST /sessions`.
The web server is supposed to create the Session and open this page with
`?token=…&passage=…`. Set the URLs in `js/config.js`.

## Files

| File | What it does |
|---|---|
| `index.html` | All screens: start, calibration overlay, reading, results and "session ended" modals |
| `css/styles.css` | Styles (colors are variables at the top) |
| `js/config.js` | Settings: mock on/off, service URLs, frame rate, calibration timing |
| `js/app.js` | Main flow: screens, sending `layout` / `frame` / `calibration_*`, handling replies |
| `js/face-tracker.js` | Webcam + MediaPipe Face Landmarker → the `frame` landmark subset |
| `js/connection.js` | Same interface for the real WebSocket and the mock |
| `js/mock-service.js` | Fake service for testing without the backend |
| `js/passage.js` | Braille table and default Passage (same as `passage.py`) |

## Things to check / to do

- **Matrix order**: `face-tracker.js` transposes MediaPipe's matrix (column-major → row-major) as the
  protocol doc says. The doc asks to verify this against real output.
- **Protocol v2** (`eye_centres`, Timm & Barth in the browser) is not implemented; we send version 1.
- **No scrolling or resizing** during a Session: it sends `viewport_changed` and the Session ends.
