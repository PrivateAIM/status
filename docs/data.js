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
    else if (resultStr == "failed" || resultStr == "failure") result = 0;

    entries.push({
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

export function normalizeData(statusLines) {
  const rows = statusLines.split("\n");
  const parsedRows = parseRows(rows);

  const slotMs = getSlotMs();
  const now = Date.now();

  let relativeSlotMap = {};
  let sum = 0, count = 0, unknownCount = 0, slotsWithData = 0;

  for (const entry of parsedRows) {
    const age = now - entry.timestamp;
    if (age < 0) continue;
    const relSlot = Math.floor(age / slotMs);
    if (relSlot >= CONFIG.maxBlocks) continue;

    if (!relativeSlotMap[relSlot]) {
      relativeSlotMap[relSlot] = { results: [], durations: [] };
    }

    relativeSlotMap[relSlot].results.push(entry.result);
    if (entry.duration !== null && entry.result === 1) {
      relativeSlotMap[relSlot].durations.push(entry.duration);
    }
  }

  // Aggregate each slot
  for (const [slot, data] of Object.entries(relativeSlotMap)) {
    slotsWithData++;
    const validResults = data.results.filter(r => r !== -1);
    const slotUnknowns = data.results.filter(r => r === -1).length;
    
    sum += validResults.reduce((a, b) => a + b, 0);
    count += validResults.length;
    unknownCount += slotUnknowns;

    relativeSlotMap[slot] = {
      uptime: validResults.length > 0 ? getAverage(validResults) : null,
      duration: data.durations.length > 0 ? getAverage(data.durations) : null,
    };
  }

  const validRows = rows.filter(r => r.trim().length > 0);
  const lookbackMs = CONFIG.statusLookbackMinutes * 60000;
  let recentResults = [];
  let recentDurations = [];
  
  for (const row of validRows) {
    const parts = row.split(",");
    const dateTimeStr = parts[0];
    const timestamp = Date.parse(dateTimeStr.replace(/-/g, "/") + " GMT");
    if (isNaN(timestamp)) continue;
    
    if (now - timestamp <= lookbackMs && now - timestamp >= 0) {
      const resultStr = parts[1] ? parts[1].trim() : "";
      const duration = parts[2] ? parseFloat(parts[2].trim()) : null;

      if (resultStr === "success") {
        recentResults.push(1);
        if (duration !== null && !isNaN(duration)) recentDurations.push(duration);
      } else if (resultStr === "failed" || resultStr === "failure") {
        recentResults.push(0);
      }
    }
  }
  relativeSlotMap.overallUptime = recentResults.length > 0 ? getAverage(recentResults) : null;
  relativeSlotMap.overallDuration = recentDurations.length > 0 ? getAverage(recentDurations) : null;

  const ignoredUptime = count ? ((sum / count) * 100).toFixed(2) + "%" : "--%";
  const strictUptime = (count + unknownCount) ? ((sum / (count + unknownCount)) * 100).toFixed(2) + "%" : "--%";
  relativeSlotMap.upTime = `${ignoredUptime} (${strictUptime})`;
  relativeSlotMap.coveredLabel = formatCoveredLabel(slotsWithData);
  
  const allDurations = parsedRows
    .filter(entry => entry.result === 1)
    .map(entry => entry.duration)
    .filter(d => d !== null && !isNaN(d));
  relativeSlotMap.avgDuration = allDurations.length > 0 ? getAverage(allDurations) : null;

  relativeSlotMap.latestDuration = parsedRows.length > 0 ? parsedRows[parsedRows.length - 1].duration : null;
  relativeSlotMap.latestTimestamp = parsedRows.length > 0 ? new Date(parsedRows[parsedRows.length - 1].timestamp) : null;
  return relativeSlotMap;
}
