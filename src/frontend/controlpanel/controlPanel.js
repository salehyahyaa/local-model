import { refreshAlarms, setupAlarms, stopAlarms } from "./alarmsView.js";
import * as api from "./controlPanelApi.js";

const REFRESH_MS = 60000;
const REFRESH_WHILE_SCANNING_MS = 4000;
const DAY_MS = 86400000;
const SOON_DAYS = 3;
const PAGE_ADDRESS = "#control-panel";
const CHECK_ICON =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="5 12.5 10 17.5 19 7"/></svg>';
const OPEN_ICON =
  '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 5h5v5"/><path d="M19 5l-9 9"/><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/></svg>';

const panel = document.getElementById("control-panel");
const chatView = document.querySelector(".main");
const openButton = document.getElementById("control-panel-button");
const lastScan = document.getElementById("cp-last-scan");
const todoCount = document.getElementById("cp-todo-count");
const todoStatus = document.getElementById("cp-todo-status");
const todoList = document.getElementById("cp-todo-list");
const completed = document.getElementById("cp-completed");
const completedCount = document.getElementById("cp-completed-count");
const completedList = document.getElementById("cp-completed-list");

let refreshTimer = null;
let latestTasks = null;

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function showMessage(list, text, className = "cp-empty") {
  list.replaceChildren(createElement("li", className, text));
}

function showSkeleton(list, count) {
  const rows = Array.from({ length: count }, () => {
    const row = createElement("li", "cp-skeleton");
    row.setAttribute("aria-hidden", "true");
    return row;
  });
  list.replaceChildren(...rows);
}

function daysUntil(isoDate) {
  const [year, month, day] = isoDate.split("-").map(Number);
  const today = new Date();
  const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((new Date(year, month - 1, day) - startOfToday) / DAY_MS);
}

function describeDeadline(isoDate) {
  const days = daysUntil(isoDate);
  if (days < 0) return { text: "Overdue", tone: "overdue" };
  if (days === 0) return { text: "Due today", tone: "overdue" };
  if (days === 1) return { text: "Due tomorrow", tone: "soon" };
  return { text: `Due in ${days} days`, tone: days <= SOON_DAYS ? "soon" : "later" };
}

function formatDay(value) {
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function formatTimeAgo(value) {
  const minutes = Math.round((Date.now() - new Date(value)) / 60000);
  if (minutes < 1) return "Checked just now";
  if (minutes < 60) return `Checked ${minutes} min ago`;
  return `Checked ${new Date(value).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`;
}

function showTasks(tasks) {
  latestTasks = tasks;
  renderTasks(tasks);
  scheduleRefresh(tasks.scanning);
}

async function changeTask(button, change, taskId) {
  button.disabled = true;
  try {
    showTasks(await change(taskId));
  } catch (error) {
    button.disabled = false;
    showStatus(error.message);
  }
}

function createOpenLink(task) {
  const link = createElement("a", "cp-icon-link");
  link.href = task.gmailUrl;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.title = "Open in Gmail";
  link.setAttribute("aria-label", `Open in Gmail: ${task.title}`);
  link.innerHTML = OPEN_ICON;
  return link;
}

function createOpenTask(task) {
  const row = createElement("li", "cp-task");
  const check = createElement("button", "cp-check");
  check.type = "button";
  check.title = "Mark done";
  check.setAttribute("aria-label", `Mark done: ${task.title}`);
  check.innerHTML = CHECK_ICON;
  check.addEventListener("click", () => changeTask(check, api.completeTask, task.id));

  const body = createElement("div", "cp-task-body");
  body.append(createElement("div", "cp-task-title", task.title));
  const details = [task.company, formatDay(task.emailDate)].filter(Boolean).join(" · ");
  body.append(createElement("div", "cp-task-meta", details));

  row.append(check, body);
  if (task.deadline) {
    const deadline = describeDeadline(task.deadline);
    row.append(createElement("span", `cp-chip ${deadline.tone}`, deadline.text));
  }
  if (task.gmailUrl) row.append(createOpenLink(task));
  return row;
}

function createClosedTask(task) {
  const row = createElement("li", "cp-task closed");
  const body = createElement("div", "cp-task-body");
  body.append(createElement("div", "cp-task-title", task.title));
  const how = task.closedBy === "email" ? "Confirmed by email" : "Marked done";
  body.append(createElement("div", "cp-task-meta", [task.company, how].filter(Boolean).join(" · ")));
  const undo = createElement("button", "cp-text-button", "Undo");
  undo.type = "button";
  undo.setAttribute("aria-label", `Undo: ${task.title}`);
  undo.addEventListener("click", () => changeTask(undo, api.reopenTask, task.id));
  row.append(body, undo);
  return row;
}

function showStatus(text) {
  todoStatus.textContent = text;
  todoStatus.hidden = !text;
}

function describeScanStatus(tasks) {
  if (!tasks.gmailConnected) return "Connect Gmail from the + menu to find unfinished work in your email.";
  if (tasks.lastError) return tasks.lastError;
  if (!tasks.modelConnected) {
    return tasks.waitingCount > 0
      ? `${tasks.waitingCount} emails are waiting for a model to check them.`
      : "Emails will be checked once a model is connected.";
  }
  if (tasks.catchingUp) return "Catching up on your recent email. More tasks may appear as it goes.";
  return "";
}

function describeEmptyList(tasks) {
  if (!tasks.gmailConnected || !tasks.modelConnected) return "Nothing to show yet.";
  if (tasks.scanning || tasks.catchingUp) return "Nothing found so far.";
  return "You're all caught up.";
}

function renderTasks(tasks) {
  showStatus(describeScanStatus(tasks));
  todoCount.hidden = tasks.open.length === 0;
  todoCount.textContent = tasks.open.length;
  if (tasks.open.length > 0) {
    todoList.replaceChildren(...tasks.open.map(createOpenTask));
  } else {
    showMessage(todoList, describeEmptyList(tasks));
  }

  completed.hidden = tasks.completed.length === 0;
  completedCount.textContent = tasks.completed.length;
  completedList.replaceChildren(...tasks.completed.map(createClosedTask));

  lastScan.textContent = tasks.lastScanAt ? formatTimeAgo(tasks.lastScanAt) : "";
}

function scheduleRefresh(isScanning) {
  clearTimeout(refreshTimer);
  if (panel.hidden) return;
  refreshTimer = setTimeout(refreshTasks, isScanning ? REFRESH_WHILE_SCANNING_MS : REFRESH_MS);
}

async function refreshTasks() {
  try {
    showTasks(await api.loadTasks());
  } catch (error) {
    if (!latestTasks) {
      showMessage(todoList, "Your To Do list couldn't load.", "cp-error");
    }
    showStatus(error.message);
    scheduleRefresh(false);
  }
}

export function openControlPanel() {
  openPanel();
}

function openPanel() {
  document.dispatchEvent(new CustomEvent("main-view-opened", { detail: "control-panel" }));
  chatView.hidden = true;
  panel.hidden = false;
  openButton.classList.add("active");
  openButton.setAttribute("aria-pressed", "true");
  history.replaceState(null, "", PAGE_ADDRESS);
  if (!latestTasks) showSkeleton(todoList, 4);
  refreshTasks();
  refreshAlarms();
}

function closePanel() {
  clearTimeout(refreshTimer);
  stopAlarms();
  panel.hidden = true;
  chatView.hidden = false;
  openButton.classList.remove("active");
  openButton.setAttribute("aria-pressed", "false");
  history.replaceState(null, "", location.pathname);
}

export function setupControlPanel() {
  setupAlarms();
  openButton.setAttribute("aria-pressed", "false");
  openButton.addEventListener("click", () => (panel.hidden ? openPanel() : closePanel()));
  document.getElementById("sidebar").addEventListener("click", (event) => {
    if (!panel.hidden && event.target.closest(".chat-title-button, #new-chat-button")) closePanel();
  });
  document.addEventListener("main-view-opened", (event) => {
    if (event.detail !== "control-panel" && !panel.hidden) closePanel();
  });
  if (location.hash === PAGE_ADDRESS) openPanel();
}
