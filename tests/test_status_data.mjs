import assert from "node:assert/strict";
import { normalizeData, worstResult } from "../docs/data.js";
import { getReportColor } from "../docs/ui.js";

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
console.log("Dashboard status regression checks passed.");
