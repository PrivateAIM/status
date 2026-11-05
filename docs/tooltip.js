import { formatSlotDate } from "./data.js";
import { getStatusText, getStatusDescriptiveText } from "./constants.js";

function hasTooltipSelection() {
  const selection = window.getSelection();
  const tooltip = document.getElementById("tooltip");
  return selection && !selection.isCollapsed && tooltip &&
    (tooltip.contains(selection.anchorNode) || tooltip.contains(selection.focusNode));
}

export function initTooltip() {
  const tooltip = document.getElementById("tooltip");
  if (!tooltip) return;
  // Stay open while the user moves the pointer or selects/copies text.
  document.addEventListener("pointerdown", (event) => {
    if (!tooltip.contains(event.target) && !event.target.closest?.(".statusSquare")) hideTooltip();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      hideTooltip();
    }
  });
}

export function formatCheckTimes(firstTimestamp, lastTimestamp) {
  if (!firstTimestamp || !lastTimestamp) return "No recorded checks";
  const first = formatSlotDate(new Date(Number(firstTimestamp)));
  const last = formatSlotDate(new Date(Number(lastTimestamp)));
  return firstTimestamp === lastTimestamp ? `Check: ${last}` : `Checks: ${first} – ${last}`;
}

export function showTooltip(element, key, color, duration) {
  if (hasTooltipSelection()) return;
  const toolTipDiv = document.getElementById("tooltip");
  if (!toolTipDiv) return;

  const dateTimeEl = document.getElementById("tooltipDateTime");
  if (dateTimeEl) dateTimeEl.innerText = formatCheckTimes(element.dataset.firstTimestamp, element.dataset.lastTimestamp);

  let descText = getStatusDescriptiveText(color);
  if (duration !== null && duration !== undefined && (color === "success" || color === "partial")) {
    descText += `\nAverage run duration: ${duration.toFixed(1)}s.`;
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

  toolTipDiv.classList.add("is-visible");
}

export function hideTooltip() {
  document.getElementById("tooltip")?.classList.remove("is-visible");
}

export function showTooltipForSquare(square) {
  const key = square.dataset.key;
  const color = square.dataset.status;
  const duration = square.dataset.duration ? parseFloat(square.dataset.duration) : null;
  showTooltip(square, key, color, duration);
}
