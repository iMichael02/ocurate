// Times the frontend's detect() for REQ-03. Dev tool (see benchmark/browser_timing.py).
// Runs at the frontend's frame cap, alternating frames without and with eye centres. Only numbers leave the page.

import { CONFIG } from "/fe/js/config.js";
import { startCamera, stopCamera, loadLandmarker, detect } from "/fe/js/camera/face-tracker.js";

const $ = (id) => document.getElementById(id);
const WARMUP_FRAMES = 40;
const SAMPLES_PER_GROUP = 200;
const say = (t) => { $("status").textContent = t; };

const median = (a) => { const s = [...a].sort((x, y) => x - y); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const percentile = (a, p) => [...a].sort((x, y) => x - y)[Math.min(a.length - 1, Math.floor(p * a.length))];
const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
const round = (v) => Math.round(v * 1000) / 1000;
const summary = (a) => ({ n: a.length, median_ms: round(median(a)), p95_ms: round(percentile(a, 0.95)), mean_ms: round(mean(a)) });

function measure(video) {
  return new Promise((resolve) => {
    const without = [], withCentres = [];
    let tick = 0, noFace = 0, last = 0, frames = 0, first = 0;

    function loop(now) {
      if (without.length >= SAMPLES_PER_GROUP && withCentres.length >= SAMPLES_PER_GROUP) {
        return resolve({ without, withCentres, noFace, frames, seconds: (now - first) / 1000 });
      }
      requestAnimationFrame(loop);
      if (now - last < 1000 / CONFIG.maxFps) return;
      last = now;
      if (!first) first = now;
      frames++;

      const centres = tick % 2 === 1;
      const started = performance.now();
      const frame = detect(video, now, centres);
      const elapsed = performance.now() - started;
      tick++;

      if (!frame) { noFace++; return; }
      if (tick <= WARMUP_FRAMES) return;
      (centres ? withCentres : without).push(elapsed);
      say(`Measuring… ${without.length + withCentres.length} / ${SAMPLES_PER_GROUP * 2}`);
    }
    requestAnimationFrame(loop);
  });
}

async function run() {
  $("btn-start").disabled = true;
  const r = await measure($("video"));
  stopCamera();

  const body = {
    without_centres: summary(r.without),
    with_centres: summary(r.withCentres),
    no_face: r.noFace,
    frames: r.frames,
    achieved_fps: round(r.frames / r.seconds),
    user_agent: navigator.userAgent,
    cores: navigator.hardwareConcurrency,
  };
  $("out").textContent = JSON.stringify(body, null, 2);

  const response = await fetch("/result", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  say(response.ok ? "Done. The result was sent to the local server." : "Done, but the server did not accept the result. Copy the numbers below.");
}

$("btn-camera").addEventListener("click", async () => {
  $("btn-camera").disabled = true;
  try {
    $("video").srcObject = await startCamera();
    say("Loading the face model…");
    await loadLandmarker();
    say("Camera ready. Keep your face in view.");
    $("btn-start").disabled = false;
  } catch {
    say("The camera or the face model could not start (the model loads from the internet).");
    $("btn-camera").disabled = false;
  }
});
$("btn-start").addEventListener("click", () => run().catch(() => say("Measurement failed.")));
