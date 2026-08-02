import {
  getIngestionWindow,
  isWithinWindow,
  isAfterWindow,
  isBeforeWindow,
  describeWindow,
} from "../src/services/time-window.service.js";

// Offline test of the training time window logic (default window:
// 2025-06-01 -> 2026-06-30, overridable via INGEST_WINDOW_START/_END).
const window = getIngestionWindow();
console.log(`window under test: ${describeWindow(window)}`);

const inside = Date.parse("2025-12-15T12:00:00Z");
const before = Date.parse("2024-01-01T00:00:00Z");
const after = Date.parse("2026-07-06T00:00:00Z");

console.assert(isWithinWindow(inside, window), "inside should be within window");
console.assert(!isWithinWindow(before, window), "before should not be within window");
console.assert(!isWithinWindow(after, window), "after should not be within window");

console.assert(isBeforeWindow(before, window), "before should be before window");
console.assert(!isBeforeWindow(inside, window), "inside should not be before window");

console.assert(isAfterWindow(after, window), "after should be after window");
console.assert(!isAfterWindow(inside, window), "inside should not be after window");

// Boundaries are inclusive.
console.assert(isWithinWindow(window.startMs, window), "start boundary inclusive");
console.assert(isWithinWindow(window.endMs, window), "end boundary inclusive");

console.log("✅ time-window smoke test passed");
