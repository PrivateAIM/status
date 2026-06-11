const maxDays = 30;

async function genReportLog(container, key, url) {
  const response = await fetch("logs/" + key + "_report.log");
  let statusLines = "";
  if (response.ok) {
    statusLines = await response.text();
  }

  const normalized = normalizeData(statusLines);
  const statusStream = constructStatusStream(key, url, normalized);
  container.appendChild(statusStream);
}

function constructStatusStream(key, url, uptimeData) {
  let streamContainer = templatize("statusStreamContainerTemplate");
  for (var ii = maxDays - 1; ii >= 0; ii--) {
    let line = constructStatusLine(key, ii, uptimeData[ii]);
    streamContainer.appendChild(line);
  }

  const lastSet = uptimeData[0];
  const lastUptime = lastSet ? lastSet.uptime : null;
  const color = getColor(lastUptime);

  const durationText = uptimeData.latestDuration !== null && uptimeData.latestDuration !== undefined
    ? `Latest run: ${uptimeData.latestDuration.toFixed(1)}s`
    : "Latest run: --";

  const container = templatize("statusContainerTemplate", {
    title: key,
    url: url,
    color: color,
    status: getStatusText(color),
    upTime: uptimeData.upTime,
    upDays: uptimeData.daysWithData + "d",
    latestDuration: durationText,
  });

  container.appendChild(streamContainer);
  return container;
}

function constructStatusLine(key, relDay, dayData) {
  let date = new Date();
  date.setDate(date.getDate() - relDay);

  return constructStatusSquare(key, date, dayData);
}

function getColor(uptimeVal) {
  return uptimeVal == null
    ? "nodata"
    : uptimeVal == 1
    ? "success"
    : uptimeVal < 0.3
    ? "failure"
    : "partial";
}

function constructStatusSquare(key, date, dayData) {
  const uptimeVal = dayData ? dayData.uptime : null;
  const durationVal = dayData ? dayData.duration : null;
  const color = getColor(uptimeVal);

  let square = templatize("statusSquareTemplate", {
    color: color,
    tooltip: getTooltip(key, date, color, durationVal),
  });

  const show = () => {
    showTooltip(square, key, date, color, durationVal);
  };
  square.addEventListener("mouseover", show);
  square.addEventListener("mousedown", show);
  square.addEventListener("mouseout", hideTooltip);
  return square;
}

let cloneId = 0;
function templatize(templateId, parameters) {
  let clone = document.getElementById(templateId).cloneNode(true);
  clone.id = "template_clone_" + cloneId++;
  if (!parameters) {
    return clone;
  }

  applyTemplateSubstitutions(clone, parameters);
  return clone;
}

function applyTemplateSubstitutions(node, parameters) {
  const attributes = node.getAttributeNames();
  for (var ii = 0; ii < attributes.length; ii++) {
    const attr = attributes[ii];
    const attrVal = node.getAttribute(attr);
    node.setAttribute(attr, templatizeString(attrVal, parameters));
  }

  if (node.childElementCount == 0) {
    node.innerText = templatizeString(node.innerText, parameters);
  } else {
    const children = Array.from(node.children);
    children.forEach((n) => {
      applyTemplateSubstitutions(n, parameters);
    });
  }
}

function templatizeString(text, parameters) {
  if (parameters) {
    for (const [key, val] of Object.entries(parameters)) {
      text = text.replaceAll("$" + key, val);
    }
  }
  return text;
}

function getStatusText(color) {
  return color == "nodata"
    ? "No Data Available"
    : color == "success"
    ? "Fully Operational"
    : color == "failure"
    ? "Major Outage"
    : color == "partial"
    ? "Partial Outage"
    : "Unknown";
}

function getStatusDescriptiveText(color) {
  return color == "nodata"
    ? "No Data Available: Health check was not performed."
    : color == "success"
    ? "No downtime recorded on this day."
    : color == "failure"
    ? "Major outages recorded on this day."
    : color == "partial"
    ? "Partial outages recorded on this day."
    : "Unknown";
}

function getTooltip(key, date, color, duration) {
  let statusText = getStatusText(color);
  const durText = duration !== null && duration !== undefined ? ` (${duration.toFixed(1)}s)` : "";
  return `${key} | ${date.toDateString()} : ${statusText}${durText}`;
}

function create(tag, className) {
  let element = document.createElement(tag);
  element.className = className;
  return element;
}

function normalizeData(statusLines) {
  const rows = statusLines.split("\n");
  const dateNormalized = splitRowsByDate(rows);

  let relativeDateMap = {};
  const now = Date.now();
  // Uptime is computed only over days inside the display window that
  // actually have log entries; daysWithData is the covered period.
  let sum = 0,
    count = 0,
    daysWithData = 0;
  for (const [key, val] of Object.entries(dateNormalized)) {
    if (key == "latestDuration") {
      continue;
    }

    const relDays = getRelativeDays(now, new Date(key).getTime());
    relativeDateMap[relDays] = {
      uptime: getAverage(val.results),
      duration: getAverage(val.durations),
    };

    if (relDays < maxDays && val.results.length > 0) {
      daysWithData++;
      sum += val.results.reduce((a, b) => a + b, 0);
      count += val.results.length;
    }
  }

  relativeDateMap.upTime = count ? ((sum / count) * 100).toFixed(2) + "%" : "--%";
  relativeDateMap.daysWithData = daysWithData;
  relativeDateMap.latestDuration = dateNormalized.latestDuration;
  return relativeDateMap;
}

function getAverage(arr) {
  if (!arr || arr.length === 0) {
    return null;
  }
  const valid = arr.filter((v) => v !== null && !isNaN(v));
  if (valid.length === 0) {
    return null;
  }
  return valid.reduce((a, b) => a + b, 0) / valid.length;
}

function getRelativeDays(date1, date2) {
  return Math.floor(Math.abs((date1 - date2) / (24 * 3600 * 1000)));
}

function splitRowsByDate(rows) {
  let dateValues = {};
  let latestDuration = null;

  for (var ii = 0; ii < rows.length; ii++) {
    const row = rows[ii];
    if (!row) {
      continue;
    }

    const parts = row.split(",");
    const dateTimeStr = parts[0];
    const resultStr = parts[1] ? parts[1].trim() : "";
    const duration = parts[2] ? parseFloat(parts[2].trim()) : null;

    // "unknown" means the step never ran (an earlier step failed);
    // exclude it from uptime statistics instead of counting it as failure.
    if (resultStr == "unknown") {
      continue;
    }

    const dateTime = new Date(Date.parse(dateTimeStr.replace(/-/g, "/") + " GMT"));
    const dateStr = dateTime.toDateString();

    let dayData = dateValues[dateStr];
    if (!dayData) {
      dayData = { results: [], durations: [] };
      dateValues[dateStr] = dayData;
    }

    let result = 0;
    if (resultStr == "success") {
      result = 1;
    }
    dayData.results.push(result);
    if (duration !== null && !isNaN(duration)) {
      dayData.durations.push(duration);
      latestDuration = duration;
    }
  }

  dateValues.latestDuration = latestDuration;
  return dateValues;
}

let tooltipTimeout = null;
function showTooltip(element, key, date, color, duration) {
  clearTimeout(tooltipTimeout);
  const toolTipDiv = document.getElementById("tooltip");

  document.getElementById("tooltipDateTime").innerText = date.toDateString();
  
  let descText = getStatusDescriptiveText(color);
  if (duration !== null && duration !== undefined && color === "success") {
    descText += ` Average run duration: ${duration.toFixed(1)}s.`;
  }
  document.getElementById("tooltipDescription").innerText = descText;

  const statusDiv = document.getElementById("tooltipStatus");
  statusDiv.innerText = getStatusText(color);
  statusDiv.className = color;

  const rect = element.getBoundingClientRect();
  toolTipDiv.style.top = rect.bottom + window.scrollY + 10 + "px";
  toolTipDiv.style.left =
    rect.left + window.scrollX + rect.width / 2 - toolTipDiv.offsetWidth / 2 + "px";
  toolTipDiv.style.opacity = "1";
}

function hideTooltip() {
  tooltipTimeout = setTimeout(() => {
    const toolTipDiv = document.getElementById("tooltip");
    toolTipDiv.style.opacity = "0";
  }, 1000);
}

async function genMessages() {
  const container = document.getElementById("messages");
  const response = await fetch("messages.json");
  if (!response.ok) {
    return;
  }

  const messages = await response.json();
  messages.sort((a, b) => new Date(b.date) - new Date(a.date));

  for (const msg of messages) {
    const card = create("div", "messageCard " + msg.type);

    const header = create("div", "messageHeader");
    const title = create("span", "messageTitle");
    title.innerText = msg.title;
    const date = create("span", "messageDate");
    date.innerText = msg.date;
    header.appendChild(title);
    header.appendChild(date);

    const text = create("div", "messageText");
    text.innerText = msg.text;

    card.appendChild(header);
    card.appendChild(text);
    container.appendChild(card);
  }
}

async function genAllReports() {
  const response = await fetch("urls.cfg");
  const configText = await response.text();
  const configLines = configText.split("\n");
  for (let ii = 0; ii < configLines.length; ii++) {
    const configLine = configLines[ii];
    const [key, url] = configLine.split("=");
    if (!key || !url) {
      continue;
    }

    await genReportLog(document.getElementById("reports"), key, url);
  }
}
