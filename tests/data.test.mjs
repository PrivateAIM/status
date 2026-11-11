import test from "node:test";
import assert from "node:assert/strict";
import { normalizeData, parseRows } from "../docs/data.js";
import { state } from "../docs/state.js";

test("old and new rows retain their results and optional run URLs", () => {
  const rows = parseRows([
    "2026-11-11 11:00, success, 12.50",
    "2026-11-11 11:30, failed, , https://github.com/example/status/actions/runs/1/attempts/2",
    "2026-11-11 11:45, unknown, , ",
    "invalid, success, 12",
  ]);
  assert.equal(rows.length, 3);
  assert.deepEqual(rows.map(r => r.result), [1, 0, -1]);
  assert.deepEqual(rows.map(r => r.duration), [12.5, null, null]);
  assert.equal(rows[0].runUrl, null);
  assert.equal(rows[1].runUrl, "https://github.com/example/status/actions/runs/1/attempts/2");
});

test("contributing checks follow the selected resolution without changing aggregation", () => {
  const originalNow = Date.now;
  const originalResolution = state.currentResolution;
  Date.now = () => Date.parse("2026-11-11T12:00:00Z");
  const logs = [
    "2026-11-11 11:50, success, 10, https://github.com/example/status/actions/runs/1/attempts/1",
    "2026-11-11 11:48, failed, , https://github.com/example/status/actions/runs/2/attempts/1",
    "2026-11-11 11:46, unknown, , ",
    "2026-11-11 10:00, success, 30",
    "2026-11-11 13:00, success, 50",
  ].join("\n");
  try {
    state.currentResolution = "15min";
    const short = normalizeData(logs);
    assert.equal(short[0].entries.length, 3);
    assert.equal(short[0].uptime, 0);
    assert.equal(short[0].duration, 10);
    assert.equal(short[7].entries[0].runUrl, null);
    assert.ok(short[0].entries[0].timestamp > short[0].entries[1].timestamp);
    state.currentResolution = "1d";
    const daily = normalizeData(logs);
    assert.equal(daily[0].entries.length, 4);
    assert.equal(daily[0].uptime, 0);
    assert.equal(daily[0].duration, 20);
  } finally {
    Date.now = originalNow;
    state.currentResolution = originalResolution;
  }
});

test("partial checks keep their category and contributing run", () => {
  const row = "2020-01-01 11:50, partial, 40, https://github.com/example/status/actions/runs/3/attempts/1";
  const entry = parseRows([row])[0];
  assert.equal(entry.result, 0.5);
  const normalized = normalizeData(row);
  assert.equal(normalized[0].uptime, 0.5);
  assert.equal(normalized[0].entries[0].runUrl, entry.runUrl);
});
