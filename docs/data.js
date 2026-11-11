import { CONFIG } from "./constants.js";
import { state } from "./state.js";

export function getSlotMs() {
  return CONFIG.resolutions[state.currentResolution].ms;
}

export function formatSlotDate(date) {
  if (state.currentResolution === "1d") {
    return date.toDateString();
  }
  return date.toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export function formatCoveredLabel(slotsWithData) {
  if (state.currentResolution === "1d") {
    return slotsWithData + "d";
  }
  const totalHours = slotsWithData * (getSlotMs() / 3600000);
  if (totalHours >= 24) {
    return (totalHours / 24).toFixed(1) + "d";
  }
  return totalHours.toFixed(1) + "h";
}

export function parseRows(rows) {
  let entries = [];
  for (var ii = 0; ii < rows.length; ii++) {
    const row = rows[ii];
    if (!row) continue;

    const parts = row.split(",");
    const dateTimeStr = parts[0];
    const resultStr = parts[1] ? parts[1].trim() : "";
    const duration = parts[2] ? parseFloat(parts[2].trim()) : null;

    const timestamp = Date.parse(dateTimeStr.replace(/-/g, "/") + " GMT");
    if (isNaN(timestamp)) continue;

    let result = -1;
    if (resultStr == "success") result = 1;
    else if (resultStr == "partial") result = 0.5;
    else if (resultStr == "failed" || resultStr == "failure") result = 0;

    entries.push({
      runUrl: parts[3] ? parts[3].trim() : null,
      timestamp: timestamp,
      result: result,
      duration: duration !== null && !isNaN(duration) ? duration : null,
    });
  }
  return entries;
}

export function getAverage(arr) {
  if (!arr || arr.length === 0) {
    return null;
  }
  const valid = arr.filter((v) => v !== null && !isNaN(v));
  if (valid.length === 0) {
    return null;
  }
  return valid.reduce((a, b) => a + b, 0) / valid.length;
}

// Partial is a category, not a measured 50% node uptime. Count only fully
// successful runs in uptime statistics; use the worst category for colors.
export function worstResult(results) {
  if (results.includes(0)) return 0;
  if (results.includes(0.5)) return 0.5;
  if (results.includes(1)) return results.includes(-1) ? 0.5 : 1;
  return null;
}

export function normalizeData(statusLines, referenceTime) {
  const parsedRows = parseRows(statusLines.split("\n"));
  const now = Date.now();
  const recorded = parsedRows.filter(entry => entry.timestamp <= now);
  const latest = recorded.reduce((last, entry) => !last || entry.timestamp >= last.timestamp ? entry : last, null);
  const slotMs = getSlotMs();
  // Use fixed UTC intervals ending at the latest check, not a moving window
  // ending at page refresh time. Discord uses the same interval boundaries.
  const anchor = Math.floor((referenceTime ?? latest?.timestamp ?? now) / slotMs);
  const slots = {};
  const visible = recorded.filter(entry => {
    const slot = anchor - Math.floor(entry.timestamp / slotMs);
    return slot >= 0 && slot < CONFIG.maxBlocks;
  });
  for (const entry of visible) {
    const slot = anchor - Math.floor(entry.timestamp / slotMs);
    (slots[slot] ??= []).push(entry);
  }
  const durations = entries => entries
    .filter(entry => entry.result > 0 && entry.duration !== null)
    .map(entry => entry.duration);
  const summarize = entries => {
    const timing = durations(entries);
    return {
      entries: entries.slice().sort((a, b) => b.timestamp - a.timestamp),
      uptime: worstResult(entries.map(entry => entry.result)),
      duration: getAverage(timing),
      maxDuration: timing.length ? Math.max(...timing) : null,
      firstTimestamp: entries.length ? Math.min(...entries.map(entry => entry.timestamp)) : null,
      lastTimestamp: entries.length ? Math.max(...entries.map(entry => entry.timestamp)) : null,
    };
  };
  const normalized = {};
  for (const [slot, entries] of Object.entries(slots)) {
    normalized[slot] = summarize(entries);
  }
  const recent = parsedRows.filter(entry => now >= entry.timestamp &&
    now - entry.timestamp <= CONFIG.statusLookbackMinutes * 60000);
  const current = summarize(recent);
  normalized.overallUptime = current.uptime;
  normalized.overallDuration = current.duration;
  normalized.overallMaxDuration = current.maxDuration;

  const passed = visible.filter(entry => entry.result === 1).length;
  const known = visible.filter(entry => entry.result !== -1).length;
  const percent = total => total ? (100 * passed / total).toFixed(2) + "%" : "--%";
  normalized.upTime = `${percent(known)} (${percent(visible.length)})`;
  normalized.coveredLabel = formatCoveredLabel(Object.keys(slots).length);
  normalized.avgDuration = getAverage(durations(parsedRows));
  normalized.latestDuration = latest?.duration ?? null;
  normalized.latestTimestamp = latest ? new Date(latest.timestamp) : null;
  return normalized;
}
