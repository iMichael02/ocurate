// A fake gaze-analysis service that speaks the same protocol as the real one
// (docs/websocket-protocol.md). The backend's WebSocket endpoint is not written yet,
// so this lets the whole UI flow run today.
//
// It cannot estimate gaze, so during reading it uses the MOUSE POINTER as the gaze point:
// hover over a Cell for ~150 ms and it counts as a Fixation.

const GRID = [0.1, 0.1 + 0.8 / 3, 0.1 + 1.6 / 3, 0.9]; // 4x4, 0.1 → 0.9
const MIN_SAMPLES = 5;         // a point with fewer samples is "skipped"
const SAMPLES_PER_POINT = 20;  // when the last point has this many, calibration is judged
const FIXATION_MS = 150;
const FRAME_TIMEOUT_MS = 30000;
const MAX_ATTEMPTS = 3;

export class MockService {
  constructor(passage, emit, onClose) {
    this.passage = passage;
    this.emit = emit;
    this.onClose = onClose;
    this.state = "await_hello";
    this.pointer = null;
    this.attempt = 1;
    this.resetCalibration();
  }

  // ---- incoming messages ----
  receive(msg) {
    this.armTimeout();
    switch (msg.type) {
      case "hello":
        if (this.state !== "await_hello") return this.outOfOrder();
        if (![1, 2].includes(msg.version)) {
          this.send({ type: "error", code: "unsupported_version",
            message: `Protocol version ${msg.version} is not supported`, supported: [1, 2] });
          return this.end(4409);
        }
        this.version = msg.version;
        this.state = "await_layout";
        return this.send({ type: "hello_ack", version: msg.version, supported: [1, 2] });

      case "layout":
        if (this.state !== "await_layout") return this.outOfOrder();
        this.cells = msg.cells;
        this.state = "calibrating";
        return;

      case "frame":
        return this.onFrame(msg);

      case "calibration_restart":
        if (this.state !== "calibration_failed") return this.outOfOrder();
        this.attempt += 1;
        this.resetCalibration();
        this.state = "calibrating";
        return;

      case "calibration_done":
        if (this.state !== "calibration_ready") return this.outOfOrder();
        this.state = "reading";
        this.fix = { cell: null, since: null, emitted: false };
        this.sequence = [];
        this.started = false;
        return;

      case "viewport_changed":
        return this.abandon("viewport_changed", 1000);
      case "quit":
        return this.abandon("quit", 1000);
      default:
        this.send({ type: "error", code: "invalid_message", message: "Unknown message type" });
        return this.end(4400);
    }
  }

  onFrame(f) {
    if (this.lastT != null && f.t < this.lastT) {
      this.send({ type: "error", code: "timestamp_regression", message: "Frame time went backwards" });
      return this.abandon("protocol_error", 4400);
    }
    this.lastT = f.t;

    if (this.state === "calibrating" && f.target) return this.calibrationFrame(f.target);
    if (this.state === "reading" && !f.target) return this.readingFrame(f.t);
    // Frames between phases (e.g. while waiting for calibration_done) are ignored.
  }

  // ---- calibration ----
  resetCalibration() {
    this.points = Array.from({ length: 16 }, (_, index) => ({ index, state: "pending", samples: 0 }));
  }

  calibrationFrame(target) {
    const index = nearestGridIndex(target);
    const p = this.points[index];
    // Earlier points that were left are now ok or skipped.
    this.points.forEach((q) => {
      if (q.index < index && (q.state === "pending" || q.state === "collecting")) {
        q.state = q.samples >= MIN_SAMPLES ? "ok" : "skipped";
      }
    });
    p.state = "collecting";
    p.samples += 1;

    if (index === 15 && p.samples >= SAMPLES_PER_POINT) {
      p.state = "ok";
      return this.judgeCalibration();
    }
    if (p.samples % 5 === 1) this.sendStatus(null, null);
  }

  judgeCalibration() {
    const ok = this.points.filter((p) => p.state === "ok");
    const rows = new Set(ok.map((p) => Math.floor(p.index / 4)));
    const cols = new Set(ok.map((p) => p.index % 4));
    let reason = null;
    if (ok.length < 12) reason = "too_few_points";
    else if (rows.size < 4 || cols.size < 4) reason = "missing_row_or_column";

    if (!reason) {
      this.state = "calibration_ready";
      return this.sendStatus("ready", null);
    }
    this.sendStatus("failed", reason);
    if (this.attempt >= MAX_ATTEMPTS) {
      this.send({ type: "error", code: "calibration_failed", message: "Calibration failed" });
      return this.abandon("calibration_failed", 1000);
    }
    this.state = "calibration_failed";
  }

  sendStatus(outcome, reason) {
    this.send({
      type: "calibration_status",
      points: this.points.map((p) => ({ ...p })),
      outcome, reason, attempt: this.attempt, max_attempts: MAX_ATTEMPTS,
    });
  }

  // ---- reading (mouse pointer = gaze) ----
  readingFrame(t) {
    const cell = this.pointer ? this.cellAt(this.pointer) : null;
    const key = cell ? `${cell.row},${cell.col}` : null;

    if (key !== this.fix.cell) {
      this.fix = { cell: key, since: t, emitted: false };
      return;
    }
    if (!cell || this.fix.emitted || t - this.fix.since < FIXATION_MS) return;
    this.fix.emitted = true;
    this.onFixation(cell.row, cell.col, t);
  }

  onFixation(row, col, t) {
    const first = row === 0 && col === 0;
    const last = row === this.passage.numRows - 1 && col === this.passage.numColumns - 1;

    if (!this.started) {
      if (!first) return; // reading starts on the first Cell
      this.started = true;
      this.startT = t;
      this.send({ type: "reading_started" });
    }
    this.sequence.push({ row, col });
    this.send({ type: "fixation", row, col, t });
    if (last) this.complete(t);
  }

  complete(endT) {
    const idx = this.sequence.map((c) => c.row * this.passage.numColumns + c.col);
    let saccades = 0, regressions = 0;
    for (let i = 1; i < idx.length; i++) {
      if (idx[i] !== idx[i - 1]) saccades++;
      if (idx[i] < idx[i - 1]) regressions++;
    }
    const seen = new Set(idx);
    const maxIdx = Math.max(...idx);
    let skipped = 0;
    for (let i = 0; i <= maxIdx; i++) {
      const r = Math.floor(i / this.passage.numColumns), c = i % this.passage.numColumns;
      if (!seen.has(i) && this.passage.lines[r][c] !== " ") skipped++;
    }

    const elapsed = (endT - this.startT) / 1000;
    const minutes = Math.max(elapsed, 1e-6) / 60;
    this.state = "done";
    this.send({
      type: "completed",
      result: {
        elapsed_seconds: elapsed,
        cpm: this.passage.charCount / minutes,
        wpm: this.passage.wordCount / minutes,
        saccades, regressions,
        skipped_characters: skipped,
        sequence: this.sequence,
      },
    });
    this.end(1000);
  }

  cellAt({ x, y }) {
    return this.cells.find((c) => x >= c.x && x < c.x + c.w && y >= c.y && y < c.y + c.h) ?? null;
  }

  // ---- plumbing ----
  outOfOrder() {
    this.send({ type: "error", code: "out_of_order", message: "Message not allowed now" });
  }
  abandon(reason, code) {
    this.send({ type: "abandoned", reason });
    this.end(code);
  }
  armTimeout() {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.abandon("frame_timeout", 4408), FRAME_TIMEOUT_MS);
  }
  send(msg) {
    if (this.state === "closed") return;
    // Async, like a real socket.
    setTimeout(() => this.emit(msg), 0);
  }
  end(code) {
    if (this.state === "closed") return;
    clearTimeout(this.timer);
    setTimeout(() => { this.state = "closed"; this.onClose(code); }, 0);
  }
  close() {
    if (this.state !== "done") this.abandon("socket_closed", 1000);
  }
}

function nearestGridIndex({ x, y }) {
  const near = (v) => GRID.reduce((best, g, i) => (Math.abs(g - v) < Math.abs(GRID[best] - v) ? i : best), 0);
  return near(y) * 4 + near(x);
}
