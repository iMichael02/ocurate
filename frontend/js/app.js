// Main controller: screens, Session flow, and the messages exchanged with the service.
// Flow (docs/websocket-protocol.md):
//   hello → hello_ack → layout → frames with target (calibration) → calibration_status ready
//   → calibration_done → frames without target → reading_started → fixation… → completed

import { CONFIG } from "./config.js";
import { DEFAULT_PASSAGE, loadPassage, textToBraille } from "./passage.js";
import { startCamera, loadLandmarker, detect, syntheticFrame } from "./face-tracker.js";
import { openConnection } from "./connection.js";

const $ = (id) => document.getElementById(id);

const GRID = [0.1, 0.1 + 0.8 / 3, 0.1 + 1.6 / 3, 0.9];
const CALIB_POINTS = GRID.flatMap((y) => GRID.map((x) => ({ x, y }))); // row by row, index 0–15

const state = {
  passage: DEFAULT_PASSAGE,
  conn: null,
  phase: "idle",          // idle | connecting | calibrating | calibrated | reading | done | ended
  target: null,           // current calibration target sent with frames
  landmarkerReady: false,
  layoutSent: false,
  lastFrameT: 0,
  framesThisSecond: 0,
  fixations: 0,
  activeCell: null,
  recStart: 0,
  recTimer: null,
  calibRun: 0,
};

// ======================= Start screen =======================

$("mode-badge").textContent = CONFIG.useMock ? "Mock service" : "Live service";
$("mode-badge").className = `badge ${CONFIG.useMock ? "badge-muted" : "badge-live"}`;

$("btn-camera").addEventListener("click", async () => {
  hideError();
  $("camera-status").textContent = "Starting camera…";
  try {
    const stream = await startCamera();
    $("preview-video").srcObject = stream;
    $("session-video").srcObject = stream;
    $("camera-status").textContent = "";
    $("btn-camera").disabled = true;
  } catch (err) {
    $("camera-status").textContent = "Camera blocked";
    return showError("We need the camera. Allow it in your browser and try again.");
  }

  $("camera-status").textContent = "Loading face tracker…";
  try {
    await loadLandmarker();
    state.landmarkerReady = true;
    $("camera-status").textContent = "";
  } catch (err) {
    console.warn("MediaPipe failed to load", err);
    if (!CONFIG.useMock) return showError("Face tracker failed to load. Check your connection and reload.");
    $("camera-status").textContent = "Face tracker unavailable — mock will use a fake face";
  }
  $("btn-start").disabled = false;
});

$("btn-start").addEventListener("click", startSession);

function showError(text) {
  $("start-error").textContent = text;
  $("start-error").classList.remove("hidden");
}
function hideError() {
  $("start-error").classList.add("hidden");
}

// ======================= Session =======================

async function startSession() {
  hideError();
  const params = new URLSearchParams(location.search);

  if (!CONFIG.useMock) {
    // The web server creates the Session (POST /sessions) and hands the browser these.
    const token = params.get("token");
    if (!token) return showError("Missing session token (?token=…). The web server should provide it.");
    try {
      state.passage = await loadPassage(CONFIG.serviceHttpUrl, params.get("passage") ?? "default");
    } catch (err) {
      return showError(err.message);
    }
  }

  showScreen("session");
  renderPassage(state.passage);
  resetSessionUi();
  setPhase("connecting");

  const conn = openConnection({ token: params.get("token"), passage: state.passage });
  state.conn = conn;
  conn.onMessage = handleMessage;
  conn.onClose = (code) => {
    if (state.phase !== "done" && state.phase !== "ended") {
      endSession(code === 4401 ? "Your session link expired. Start a new session." : "Connection to the service was lost.");
    }
  };
  try {
    await conn.ready;
  } catch (err) {
    endSession(err.message);
  }
  requestAnimationFrame(frameLoop);
}

function handleMessage(msg) {
  switch (msg.type) {
    case "hello_ack":
      // Wait one frame so the Passage has its final size, then report the Cell Layout.
      requestAnimationFrame(() => {
        state.conn.send(measureLayout());
        state.layoutSent = true;
        runCalibration();
      });
      break;

    case "calibration_status":
      updateCalibrationDots(msg.points);
      $("calib-attempt").textContent = `Attempt ${msg.attempt} of ${msg.max_attempts}`;
      if (msg.outcome === "ready") onCalibrated();
      if (msg.outcome === "failed") onCalibrationFailed(msg);
      break;

    case "reading_started":
      $("reading-hint").textContent = "Reading… keep going to the last cell";
      $("progress-label").textContent = "Reading in progress…";
      break;

    case "fixation":
      onFixation(msg.row, msg.col);
      break;

    case "completed":
      state.phase = "done";
      stopRecording();
      showResults(msg.result);
      break;

    case "abandoned":
      endSession(abandonText(msg.reason));
      break;

    case "error":
      console.warn("Service error:", msg.code, msg.message);
      break;
  }
}

// ======================= Frames =======================

function frameLoop(now) {
  if (state.phase === "done" || state.phase === "ended") return;
  requestAnimationFrame(frameLoop);

  if (now - state.lastFrameT < 1000 / CONFIG.maxFps) return;
  state.lastFrameT = now;

  const video = $("session-video");
  let frame = state.landmarkerReady ? detect(video, now) : null;
  if (!frame && CONFIG.useMock && !state.landmarkerReady) frame = syntheticFrame(now);

  setTracking(Boolean(frame));
  if (!frame) return; // no face: send nothing, the service tolerates gaps

  // Only stream while the service expects frames.
  if (state.phase === "calibrating") {
    if (!state.target) return;
    frame.target = state.target;
  } else if (state.phase !== "reading") {
    return;
  }
  state.conn.send({ type: "frame", ...frame });
  state.framesThisSecond++;
}

setInterval(() => {
  $("stat-fps").textContent = state.framesThisSecond;
  state.framesThisSecond = 0;
}, 1000);

// ======================= Layout =======================

function renderPassage(passage) {
  const box = $("passage");
  box.innerHTML = "";
  box.style.gridTemplateColumns = `repeat(${passage.numColumns}, auto)`;
  passage.lines.forEach((line, row) => {
    [...textToBraille(line)].forEach((ch, col) => {
      const cell = document.createElement("span");
      cell.className = "cell";
      cell.dataset.row = row;
      cell.dataset.col = col;
      cell.textContent = ch;
      if (row === 0 && col === 0) cell.classList.add("first");
      box.appendChild(cell);
    });
  });
}

// Every Cell rectangle, normalized 0–1 to the viewport.
function measureLayout() {
  const W = window.innerWidth, H = window.innerHeight;
  const clamp = (v) => Math.min(Math.max(v, 0.0001), 0.9999);
  const cells = [...document.querySelectorAll("#passage .cell")].map((el) => {
    const r = el.getBoundingClientRect();
    const x = clamp(r.left / W), y = clamp(r.top / H);
    return {
      row: Number(el.dataset.row),
      col: Number(el.dataset.col),
      x, y,
      w: Math.min(r.width / W, 1 - x),
      h: Math.min(r.height / H, 1 - y),
    };
  });
  return { type: "layout", viewport: { width: W, height: H }, cells };
}

// Any resize, fullscreen change or scroll invalidates the calibration → Session is abandoned.
function onViewportChanged() {
  if (!state.layoutSent || state.phase === "done" || state.phase === "ended") return;
  state.conn.send({ type: "viewport_changed" });
}
window.addEventListener("resize", onViewportChanged);
window.addEventListener("scroll", onViewportChanged, true);
document.addEventListener("fullscreenchange", onViewportChanged);

// Mock only: the mouse stands in for gaze.
window.addEventListener("pointermove", (e) => {
  state.conn?.setPointer?.(e.clientX / window.innerWidth, e.clientY / window.innerHeight);
});

// ======================= Calibration =======================

async function runCalibration() {
  const run = ++state.calibRun;
  setPhase("calibrating");
  $("calibration").classList.remove("hidden");
  $("calib-failed").classList.add("hidden");
  $("calib-text").textContent = "Look at the blue dot until it moves.";
  drawCalibrationGrid();

  const dot = $("calib-target");
  for (const p of CALIB_POINTS) {
    if (run !== state.calibRun || state.phase !== "calibrating") return;
    state.target = null; // don't tag frames while the eyes travel to the new dot
    dot.style.left = `${p.x * 100}%`;
    dot.style.top = `${p.y * 100}%`;
    await sleep(CONFIG.calibrationSettleMs);
    state.target = { x: round(p.x), y: round(p.y) };
    await sleep(CONFIG.calibrationMsPerPoint - CONFIG.calibrationSettleMs);
  }
  // Keep the last dot up (still sending frames) until the service gives an outcome.
  $("calib-text").textContent = "Checking calibration…";
}

function drawCalibrationGrid() {
  const grid = $("calib-grid");
  grid.innerHTML = "";
  CALIB_POINTS.forEach((p, i) => {
    const d = document.createElement("div");
    d.className = "dot";
    d.id = `calib-dot-${i}`;
    d.style.left = `${p.x * 100}%`;
    d.style.top = `${p.y * 100}%`;
    grid.appendChild(d);
  });
}

function updateCalibrationDots(points) {
  points.forEach((p) => {
    const d = $(`calib-dot-${p.index}`);
    if (d) d.className = `dot ${p.state}`;
  });
}

function onCalibrated() {
  state.target = null;
  state.conn.send({ type: "calibration_done" });
  $("calibration").classList.add("hidden");
  setPhase("reading");
  $("reading-hint").textContent = CONFIG.useMock
    ? "Mock: move your mouse over the cells, starting top-left"
    : "Start at the top-left cell";
  $("progress-label").textContent = "Look at the first cell to begin";
  startRecording();
}

function onCalibrationFailed(msg) {
  state.target = null;
  setPhase("calibration_failed");
  const why = msg.reason === "missing_row_or_column"
    ? "A whole row or column of dots could not be used."
    : "Too many dots could not be used.";
  const left = msg.max_attempts - msg.attempt;
  $("calib-text").textContent = "Calibration didn't work";
  $("calib-failed-text").textContent =
    `${why} Make sure your face is well lit and in view. ${left} attempt${left === 1 ? "" : "s"} left.`;
  $("calib-failed").classList.toggle("hidden", left <= 0);
}

$("btn-calib-retry").addEventListener("click", () => {
  state.conn.send({ type: "calibration_restart" });
  runCalibration();
});

// ======================= Reading =======================

function onFixation(row, col) {
  state.fixations++;
  $("stat-fixations").textContent = state.fixations;
  $("stat-cell").textContent = `R${row + 1} C${col + 1}`;

  state.activeCell?.classList.remove("active");
  state.activeCell?.classList.add("read");
  const el = document.querySelector(`.cell[data-row="${row}"][data-col="${col}"]`);
  el?.classList.add("active");
  state.activeCell = el;

  const p = state.passage;
  const progress = (row * p.numColumns + col + 1) / (p.numRows * p.numColumns);
  $("progress-bar").style.width = `${Math.round(progress * 100)}%`;
}

$("btn-quit").addEventListener("click", () => state.conn?.send({ type: "quit" }));

// ======================= Results & ending =======================

function showResults(r) {
  $("res-cpm").textContent = r.cpm.toFixed(1);
  $("res-wpm").textContent = r.wpm.toFixed(1);
  $("res-time").textContent = `${r.elapsed_seconds.toFixed(1)} s`;
  $("res-saccades").textContent = r.saccades;
  $("res-regressions").textContent = r.regressions;
  $("res-skipped").textContent = r.skipped_characters;
  $("res-sequence").textContent = r.sequence.length;
  $("modal").classList.remove("hidden");
}

function endSession(text) {
  if (state.phase === "ended") return;
  setPhase("ended");
  stopRecording();
  $("calibration").classList.add("hidden");
  $("abandoned-text").textContent = text;
  $("modal-abandoned").classList.remove("hidden");
}

function abandonText(reason) {
  return {
    quit: "You quit the session. Nothing was saved.",
    viewport_changed: "The window size changed, so the calibration no longer fits. Please recalibrate.",
    frame_timeout: "We couldn't see your face for 30 seconds.",
    calibration_failed: "Calibration failed too many times. Check your lighting and try again.",
    socket_closed: "The connection was closed.",
    protocol_error: "Something went wrong talking to the service.",
  }[reason] ?? "The session ended early.";
}

const restart = () => location.reload(); // a new Session always starts fresh
$("btn-again").addEventListener("click", restart);
$("btn-modal-close").addEventListener("click", restart);
$("btn-abandoned-ok").addEventListener("click", restart);

// ======================= UI helpers =======================

function showScreen(name) {
  $("screen-start").classList.toggle("hidden", name !== "start");
  $("screen-session").classList.toggle("hidden", name !== "session");
}

function setPhase(phase) {
  state.phase = phase;
  const labels = {
    connecting: "Connecting", calibrating: "Calibrating", calibration_failed: "Calibration failed",
    reading: "Reading", done: "Done", ended: "Ended",
  };
  $("stat-phase").textContent = labels[phase] ?? phase;
}

function setTracking(on) {
  const pill = $("tracking-pill");
  pill.textContent = on ? "Tracking" : "No face";
  pill.className = `pill ${on ? "pill-on" : "pill-off"}`;
}

function resetSessionUi() {
  state.fixations = 0;
  state.activeCell = null;
  $("stat-fixations").textContent = "0";
  $("stat-cell").textContent = "—";
  $("progress-bar").style.width = "0";
}

function startRecording() {
  state.recStart = performance.now();
  $("rec-badge").classList.remove("hidden");
  state.recTimer = setInterval(() => {
    const s = Math.floor((performance.now() - state.recStart) / 1000);
    $("rec-time").textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }, 500);
}

function stopRecording() {
  clearInterval(state.recTimer);
  $("rec-badge").classList.add("hidden");
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const round = (v) => Math.round(v * 1e4) / 1e4;
