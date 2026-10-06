// Frontend settings. Change these here instead of inside the code.

export const CONFIG = {
  // true  = use the fake service in mock-service.js (works today, no backend needed)
  // false = connect to the real gaze-analysis service over WebSocket
  // You can also force it from the URL: index.html?mock=0 or ?mock=1
  useMock: true,

  // Real service (only used when useMock is false).
  // The web server normally gives the browser the session id + token after POST /sessions.
  serviceWsUrl: "ws://localhost:8000/ws",
  serviceHttpUrl: "http://localhost:8000",

  // Protocol version sent in `hello`. Version 2 also needs browser eye centres (Timm & Barth),
  // which this frontend does not compute yet, so stay on 1.
  protocolVersion: 1,

  // Frame rate cap (architecture-design.md: about 30 frames per second).
  maxFps: 30,

  // How long each calibration dot stays on screen.
  calibrationMsPerPoint: 1200,
  // Frames right after a dot moves are not tagged, so the eyes have time to land on it.
  calibrationSettleMs: 300,

  // MediaPipe Face Landmarker (runs in the browser, video never leaves it).
  mediapipeVersion: "0.10.14",
  faceModelUrl:
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
};

const param = new URLSearchParams(location.search).get("mock");
if (param === "0") CONFIG.useMock = false;
if (param === "1") CONFIG.useMock = true;
