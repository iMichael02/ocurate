import test from "node:test";
import assert from "node:assert/strict";
import { closeMessage } from "./close-message.mjs";

test("returns the correct message for each close code", () => {
  assert.equal(closeMessage(1000), "The session has ended.");
  assert.match(closeMessage(4400), /protocol error/i);
  assert.match(closeMessage(4401), /invalid/i);
  assert.match(closeMessage(4408), /timed out/i);
  assert.match(closeMessage(4409), /not supported/i);
  assert.match(closeMessage(1011), /passage/i);
  assert.match(closeMessage(1013), /full/i);
});

test("returns a fallback message for unknown close codes", () => {
  assert.equal(
    closeMessage(9999),
    "Connection to the service was lost."
  );
});
