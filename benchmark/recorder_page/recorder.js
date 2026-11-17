// Gaze benchmark recorder (docs/gaze-benchmark.md). Dev tool: not part of the service or the web interface.
//
// Reuses the frontend's own landmark code, so frames are exactly what the service would receive. Everything
// is kept in memory and posted once to the local recorder server at the end. Nothing is stored in the browser.
// Landmarks are never logged. Any window change discards the recording.

import { CONFIG } from "/fe/js/config.js";
import { startCamera, stopCamera, loadLandmarker, detect } from "/fe/js/camera/face-tracker.js";
import { makePassage } from "/fe/js/reading/passage.js";
import { renderPassage, measureLayout } from "/fe/js/session/layout.js";

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const GRID = [0.1, 0.1 + 0.8 / 3, 0.1 + 1.6 / 3, 0.9];
const POINTS = GRID.flatMap((y) => GRID.map((x) => ({ x, y })));   // row by row, index 0-15 as the service
const COUNTDOWN_S = 3;

const run = { mode: null, calibration: [], reading: [], aborted: null, lastT: 0 };
let settings;

const say = (text) => { $("status").textContent = text; };

// One capture loop for the whole recording, at most CONFIG.maxFps frames a second.
function loop(now) {
  if (run.aborted) return;
  requestAnimationFrame(loop);
  if (!run.mode || now - run.lastT < 1000 / CONFIG.maxFps) return;
  run.lastT = now;

  const frame = detect($("session-video"), now, true);   // null: no face, kept so the face share is known
  if (run.mode.kind === "calibration") run.calibration.push({ target: run.mode.index, frame });
  else run.reading.push({ row: run.mode.row, col: run.mode.col, frame });
}

function abort(reason) {
  if (run.aborted) return;
  run.aborted = reason;
  run.mode = null;
  run.calibration = [];
  run.reading = [];
  $("calibration").classList.add("hidden");
  $("cue").classList.add("hidden");
  $("screen-session").classList.add("hidden");
  $("screen-start").classList.remove("hidden");
  document.body.classList.remove("in-session");
  document.fullscreenElement && document.exitFullscreen().catch(() => {});
  $("btn-start").disabled = true;
  say(`Recording discarded: ${reason}. Reload the page to record again.`);
  stopCamera();
}

function guardWindow() {
  addEventListener("resize", () => abort("the window changed size"));
  document.addEventListener("fullscreenchange", () => !document.fullscreenElement && abort("fullscreen was left"));
  document.addEventListener("visibilitychange", () => document.hidden && abort("the tab was hidden"));
  addEventListener("keydown", (e) => e.key === "Escape" && abort("Esc was pressed"));
}

async function calibrate() {
  const dot = $("calib-target");
  $("calibration").classList.remove("hidden");
  $("calib-text").textContent = "";

  for (const [index, point] of POINTS.entries()) {
    if (run.aborted) return;
    run.mode = null;                       // not tagged while the eyes travel to the new dot
    dot.style.left = `${point.x * 100}%`;
    dot.style.top = `${point.y * 100}%`;
    dot.classList.remove("hidden");
    const shrink = dot.animate([{ transform: "scale(1)" }, { transform: "scale(0)" }],
      { duration: CONFIG.calibrationMsPerPoint, easing: "linear", fill: "forwards" });
    await sleep(CONFIG.calibrationSettleMs);
    run.mode = { kind: "calibration", index };
    await sleep(CONFIG.calibrationMsPerPoint - CONFIG.calibrationSettleMs);
    run.mode = null;
    shrink.cancel();
    dot.classList.add("hidden");
    await sleep(CONFIG.calibrationGapMs);
  }

  $("calibration").classList.add("hidden");
}

async function read(cells) {
  const cue = $("cue");
  const byKey = new Map(cells.map((c) => [`${c.row},${c.col}`, c]));
  const order = [];

  for (let pass = 0; pass < settings.passes; pass++) {
    settings.lines.forEach((line, row) => [...line].forEach((ch, col) => ch !== " " && order.push({ row, col })));
  }

  cue.classList.remove("hidden");
  for (const { row, col } of order) {
    if (run.aborted) return;
    const cell = byKey.get(`${row},${col}`);
    cue.style.left = `${(cell.x + cell.w / 2) * 100}%`;
    cue.style.top = `${(cell.y + cell.h / 2) * 100}%`;
    run.mode = { kind: "reading", row, col };   // the truth changes from this frame on; the benchmark skips the saccade
    await sleep(settings.dwell_ms);
  }
  run.mode = null;
  cue.classList.add("hidden");
}

async function upload(cells) {
  say("Saving…");
  const response = await fetch("/recording", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cells, calibration: run.calibration, reading: run.reading }),
  });
  const result = await response.json().catch(() => ({}));
  run.calibration = [];
  run.reading = [];
  return result;
}

async function record() {
  $("btn-start").disabled = true;
  try { await document.documentElement.requestFullscreen(); } catch { /* the check below catches it */ }
  await sleep(800);
  if (!document.fullscreenElement) { say("Fullscreen was refused. Allow it and try again."); $("btn-start").disabled = false; return; }

  $("screen-start").classList.add("hidden");
  $("screen-session").classList.remove("hidden");
  document.body.classList.add("in-session");
  const passage = makePassage(settings.lines);
  renderPassage(passage);
  await sleep(300);
  const cells = measureLayout().cells;           // the Layout the Learner sees, measured once, as in a live Session
  guardWindow();

  for (let s = COUNTDOWN_S; s > 0; s--) {
    $("calibration").classList.remove("hidden");
    $("calib-text").textContent = `Look at each dot as it appears. Starting in ${s}…`;
    await sleep(1000);
  }
  requestAnimationFrame(loop);
  await calibrate();
  await read(cells);
  if (run.aborted) return;

  const result = await upload(cells);
  document.fullscreenElement && document.exitFullscreen().catch(() => {});
  stopCamera();
  document.body.classList.remove("in-session");
  $("screen-session").classList.add("hidden");
  $("screen-start").classList.remove("hidden");
  run.aborted = "done";

  if (!result.saved) { say(`Not saved: ${result.reason ?? "the recorder did not accept it"}.`); return; }
  say(`Saved ${result.file}: ${result.calibration_frames} calibration and ${result.reading_frames} reading frames. You can close this page.`);
  $("warnings").replaceChildren(...(result.warnings ?? []).map((w) => Object.assign(document.createElement("li"), { textContent: w })));
}

async function init() {
  settings = await (await fetch("/config")).json();
  $("learner").textContent = settings.learner;

  $("btn-camera").addEventListener("click", async () => {
    $("btn-camera").disabled = true;
    try {
      const video = $("session-video");
      video.srcObject = await startCamera();
      say("Loading the face model…");
      await loadLandmarker();
      say("Camera ready.");
      $("btn-start").disabled = false;
    } catch {
      say("The camera or the face model could not start (the model loads from the internet).");
      $("btn-camera").disabled = false;
    }
  });
  $("btn-start").addEventListener("click", () => record().catch(() => abort("an error occurred")));
}

init();
