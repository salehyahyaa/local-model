import * as api from "./controlPanelApi.js";

const REFRESH_MS = 30000;
const ALARM_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4"/><path d="M12 17h.01"/></svg>';

const panel = document.getElementById("control-panel");
const count = document.getElementById("cp-alarms-count");
const status = document.getElementById("cp-alarms-status");
const list = document.getElementById("cp-alarms-list");
const resolved = document.getElementById("cp-alarms-resolved");
const resolvedCount = document.getElementById("cp-alarms-resolved-count");
const resolvedList = document.getElementById("cp-alarms-resolved-list");
const footer = document.getElementById("cp-alarms-footer");
const checkButton = document.getElementById("cp-alarms-check");

let refreshTimer = null;
let loaded = false;

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function formatWhen(value) {
  const date = new Date(value);
  const sameDay = date.toDateString() === new Date().toDateString();
  return sameDay
    ? date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function createActiveAlarm(alarm) {
  const row = createElement("li", "cp-task cp-alarm");
  const icon = createElement("span", "cp-alarm-icon");
  icon.innerHTML = ALARM_ICON;
  const body = createElement("div", "cp-task-body");
  body.append(createElement("div", "cp-task-title", alarm.name));
  const since = alarm.startedAt ? ` · Since ${formatWhen(alarm.startedAt)}` : "";
  body.append(createElement("div", "cp-task-meta", `${alarm.problem}${since}`));
  row.append(icon, body);
  return row;
}

function createResolvedAlarm(alarm) {
  const row = createElement("li", "cp-task closed");
  const body = createElement("div", "cp-task-body");
  body.append(createElement("div", "cp-task-title", alarm.name));
  body.append(createElement("div", "cp-task-meta", `${alarm.problem} · Fixed ${formatWhen(alarm.resolvedAt)}`));
  row.append(body);
  return row;
}

function showStatus(text) {
  status.textContent = text;
  status.hidden = !text;
}

function renderAlarms(alarms) {
  loaded = true;
  showStatus("");
  count.hidden = alarms.active.length === 0;
  count.textContent = alarms.active.length;
  if (alarms.active.length > 0) {
    list.replaceChildren(...alarms.active.map(createActiveAlarm));
  } else {
    list.replaceChildren(createElement("li", "cp-empty", alarms.lastCheckAt ? "Everything is working." : "Checking…"));
  }
  resolved.hidden = alarms.resolved.length === 0;
  resolvedCount.textContent = alarms.resolved.length;
  resolvedList.replaceChildren(...alarms.resolved.map(createResolvedAlarm));

  const checked = alarms.lastCheckAt ? `Last checked ${formatWhen(alarms.lastCheckAt)}` : "Not checked yet";
  const texting = alarms.telegramAlerts ? "Alarms are also texted on Telegram." : "Set up Telegram to get alarms texted.";
  footer.textContent = `${checked}. ${texting}`;
}

function scheduleRefresh() {
  clearTimeout(refreshTimer);
  if (panel.hidden) return;
  refreshTimer = setTimeout(refreshAlarms, REFRESH_MS);
}

export async function refreshAlarms() {
  try {
    renderAlarms(await api.loadAlarms());
  } catch (error) {
    if (!loaded) list.replaceChildren(createElement("li", "cp-error", "Alarms couldn't load."));
    showStatus(error.message);
  }
  scheduleRefresh();
}

export function stopAlarms() {
  clearTimeout(refreshTimer);
}

async function checkNow() {
  checkButton.disabled = true;
  checkButton.textContent = "Checking…";
  try {
    renderAlarms(await api.checkAlarmsNow());
  } catch (error) {
    showStatus(error.message);
  } finally {
    checkButton.disabled = false;
    checkButton.textContent = "Check now";
  }
}

export function setupAlarms() {
  checkButton.addEventListener("click", checkNow);
}
