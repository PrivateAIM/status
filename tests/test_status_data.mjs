import assert from "node:assert/strict";
import { normalizeData, worstResult } from "../docs/data.js";
import { applySquareData, getReportColor } from "../docs/ui.js";
import { formatCheckTimes } from "../docs/tooltip.js";

const now = Date.parse("2026-11-05T10:30:00Z");
Date.now = () => now;
const row = (minute, status, duration = "") => `2026-11-05 10:${minute}, ${status}, ${duration}`;
const color = (data, key = "results") => getReportColor(key, data.overallUptime, data.overallMaxDuration);

assert.equal(worstResult([1, 0.5]), 0.5);
assert.equal(worstResult([1, -1]), 0.5);
assert.equal(worstResult([-1]), null);
assert.equal(worstResult([0, 1]), 0);

for (const [statuses, expected] of [
  [["success", "success"], "success"],
  [["partial", "success"], "partial"],
  [["failed", "success"], "failure"],
  [["unknown", "success"], "partial"],
  [["unknown", "unknown"], "nodata"],
]) {
  const data = normalizeData(statuses.map((status, index) => row(27 + index, status, 1)).join("\n"));
  assert.equal(color(data), expected);
  assert.equal(getReportColor("results", data[0].uptime, data[0].maxDuration), expected);
}

const partial = normalizeData(row(27, "partial", 1));
assert.equal(partial.upTime, "0.00% (0.00%)");
assert.equal(color(partial, "latency"), "partial");
const spike = normalizeData([row(27, "success", 400), row(28, "success", 30)].join("\n"));
assert.equal(color(spike, "latency"), "failure");
assert.equal(getReportColor("latency", spike[0].uptime, spike[0].maxDuration), "failure");
const failedLatency = normalizeData(row(27, "failed"));
assert.equal(color(failedLatency, "latency"), "failure");
const future = normalizeData("2026-11-05 11:27, failed,\n" + row(27, "success", 1));
assert.equal(color(future), "success");

// A refresh after the quarter-hour must not move an old partial run into or out
// of the latest check's tile. Discord uses these same fixed UTC intervals.
const recovered = [
  "2026-11-05 13:28, partial, 0.68",
  "2026-11-05 13:42, success, 1.15",
  "2026-11-05 13:55, success, 0.77",
].join("\n");
Date.now = () => Date.parse("2026-11-05T14:01:40Z");
const before = normalizeData(recovered);
assert.equal(before[0].uptime, 1);
assert.equal(before[1].uptime, 1);
assert.equal(before[2].uptime, 0.5);
assert.equal(before[0].firstTimestamp, Date.parse("2026-11-05T13:55:00Z"));
assert.equal(before[0].lastTimestamp, Date.parse("2026-11-05T13:55:00Z"));
Date.now = () => Date.parse("2026-11-05T14:16:40Z");
assert.deepEqual(normalizeData(recovered)[0], before[0]);

const square = { dataset: { key: "results" }, className: "" };
applySquareData(square, before[0]);
assert.equal(square.dataset.lastTimestamp, String(Date.parse("2026-11-05T13:55:00Z")));
assert.equal(square.dataset.status, "success");
assert.ok(formatCheckTimes(square.dataset.firstTimestamp, square.dataset.lastTimestamp).startsWith("Check: "));
assert.ok(formatCheckTimes(String(before[1].firstTimestamp), square.dataset.lastTimestamp).startsWith("Checks: "));
const checkTime = square.dataset.lastTimestamp;
assert.ok(formatCheckTimes(checkTime, checkTime).startsWith("Check: "));
const tooltipBefore = formatCheckTimes(checkTime, checkTime);
Date.now = () => Date.parse("2026-11-05T16:16:40Z");
assert.equal(formatCheckTimes(checkTime, checkTime), tooltipBefore);
applySquareData(square, undefined);
assert.equal(formatCheckTimes(square.dataset.firstTimestamp, square.dataset.lastTimestamp), "No recorded checks");

// Use the newest timestamp across all reports so a missing source is not
// shifted forward and presented as though it belongs to the newest check.
const aligned = normalizeData(recovered, Date.parse("2026-11-05T14:10:00Z"));
assert.equal(aligned[0], undefined);
assert.equal(aligned[1].uptime, 1);
console.log("Dashboard status regression checks passed.");
