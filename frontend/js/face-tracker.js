// Webcam + MediaPipe Face Landmarker, all in the browser.
// Turns each video frame into the `frame` payload of docs/websocket-protocol.md.

import { CONFIG } from "./config.js";

// Landmark order is fixed by the protocol (mirrors eye_features.py).
const IRIS = [474, 475, 476, 477, 469, 470, 471, 472];
const EYE_CORNERS = [362, 263, 386, 374, 133, 33, 159, 145];
const NOSE_TIP = 1;

let stream = null;
let landmarker = null;

export async function startCamera() {
  if (stream) return stream;
  stream = await navigator.mediaDevices.getUserMedia({
    video: { width: 640, height: 480, facingMode: "user" },
    audio: false,
  });
  return stream;
}

export function stopCamera() {
  stream?.getTracks().forEach((t) => t.stop());
  stream = null;
}

export async function loadLandmarker() {
  if (landmarker) return landmarker;
  const base = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${CONFIG.mediapipeVersion}`;
  const { FilesetResolver, FaceLandmarker } = await import(`${base}/vision_bundle.mjs`);
  const fileset = await FilesetResolver.forVisionTasks(`${base}/wasm`);
  landmarker = await FaceLandmarker.createFromOptions(fileset, {
    baseOptions: { modelAssetPath: CONFIG.faceModelUrl, delegate: "GPU" },
    runningMode: "VIDEO",
    numFaces: 1,
    outputFacialTransformationMatrixes: true,
  });
  return landmarker;
}

const xy = (p) => ({ x: round(p.x), y: round(p.y) });
const round = (v) => Math.round(v * 1e5) / 1e5;

// MediaPipe gives a flat 16-value matrix in column-major order.
// The service reads it row-major (4 rows of 4), so transpose while reshaping.
// The protocol doc asks to verify this against real output: if head-pose features look
// wrong on the backend, swap to data[r * 4 + c].
function toRowMajor(data) {
  const rows = [];
  for (let r = 0; r < 4; r++) {
    rows.push([0, 1, 2, 3].map((c) => round(data[c * 4 + r])));
  }
  return rows;
}

/**
 * Run the landmarker on the current video frame.
 * Returns { t, iris, eye_corners, nose, matrix } or null when no face is found.
 */
export function detect(video, t) {
  if (!landmarker || video.readyState < 2) return null;
  const result = landmarker.detectForVideo(video, t);
  const face = result.faceLandmarks?.[0];
  const matrix = result.facialTransformationMatrixes?.[0];
  if (!face || !matrix) return null;

  return {
    t: round(t),
    iris: IRIS.map((i) => xy(face[i])),
    eye_corners: EYE_CORNERS.map((i) => xy(face[i])),
    nose: xy(face[NOSE_TIP]),
    matrix: toRowMajor(matrix.data),
  };
}

// Used by the mock when MediaPipe cannot load (offline, old browser):
// a plausible static face so the rest of the flow can still be tested.
export function syntheticFrame(t) {
  return {
    t: round(t),
    iris: [
      { x: 0.62, y: 0.41 }, { x: 0.63, y: 0.42 }, { x: 0.62, y: 0.43 }, { x: 0.61, y: 0.42 },
      { x: 0.38, y: 0.41 }, { x: 0.39, y: 0.42 }, { x: 0.38, y: 0.43 }, { x: 0.37, y: 0.42 },
    ],
    eye_corners: [
      { x: 0.66, y: 0.42 }, { x: 0.58, y: 0.42 }, { x: 0.62, y: 0.4 }, { x: 0.62, y: 0.44 },
      { x: 0.42, y: 0.42 }, { x: 0.34, y: 0.42 }, { x: 0.38, y: 0.4 }, { x: 0.38, y: 0.44 },
    ],
    nose: { x: 0.5, y: 0.55 },
    matrix: [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, -35], [0, 0, 0, 1]],
  };
}
