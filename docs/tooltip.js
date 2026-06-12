import { state } from "./state.js";
import { formatSlotDate, getSlotMs } from "./data.js";
import { getStatusText, getStatusDescriptiveText } from "./constants.js";

export function showTooltip(element, key, date, color, duration) {
  clearTimeout(state.tooltipTimeout);
  const toolTipDiv = document.getElementById("tooltip");
  if (!toolTipDiv) return;

  const dateTimeEl = document.getElementById("tooltipDateTime");
  if (dateTimeEl) dateTimeEl.innerText = formatSlotDate(date);

  let descText = getStatusDescriptiveText(color);
  if (duration !== null && duration !== undefined && (color === "success" || color === "partial")) {
    descText += ` Average run duration: ${duration.toFixed(1)}s.`;
  }
  const descEl = document.getElementById("tooltipDescription");
  if (descEl) descEl.innerText = descText;

  const statusDiv = document.getElementById("tooltipStatus");
  if (statusDiv) {
    statusDiv.innerText = getStatusText(color);
    statusDiv.className = "tooltipStatus " + color;
  }

  const rect = element.getBoundingClientRect();
  const tooltipWidth = toolTipDiv.offsetWidth;

  // Center the tooltip on the square, but clamp it to the viewport so it
  // doesn't overflow off-screen on narrow/mobile viewports.
  const margin = 8;
  const viewportWidth = document.documentElement.clientWidth;
  const idealLeft = rect.left + window.scrollX + rect.width / 2 - tooltipWidth / 2;
  const minLeft = window.scrollX + margin;
  const maxLeft = window.scrollX + viewportWidth - tooltipWidth - margin;
  const left = Math.min(Math.max(idealLeft, minLeft), maxLeft);

  toolTipDiv.style.top = rect.bottom + window.scrollY + 10 + "px";
  toolTipDiv.style.left = left + "px";

  // Re-point the arrow at the square's center, since the tooltip box may
  // have been shifted away from being centered on it.
  const squareCenter = rect.left + window.scrollX + rect.width / 2;
  const arrow = document.getElementById("tooltipArrow");
  if (arrow) {
    arrow.style.left = Math.min(Math.max(squareCenter - left, 12), tooltipWidth - 12) + "px";
  }

  toolTipDiv.style.opacity = "1";
}

export function hideTooltip() {
  state.tooltipTimeout = setTimeout(() => {
    const toolTipDiv = document.getElementById("tooltip");
    if (toolTipDiv) toolTipDiv.style.opacity = "0";
  }, 1000);
}

export function showTooltipForSquare(square) {
  const relSlot = parseInt(square.dataset.slot, 10);
  const date = new Date(Date.now() - relSlot * getSlotMs());
  const key = square.dataset.key;
  const color = square.dataset.status;
  const duration = square.dataset.duration ? parseFloat(square.dataset.duration) : null;
  showTooltip(square, key, date, color, duration);
}
