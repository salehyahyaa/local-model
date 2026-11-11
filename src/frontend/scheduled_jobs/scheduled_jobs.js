import * as chatStore from "../chat/chatStore.js";
import { sendMessage } from "../chat/conversation.js";
import { attachUserFiles } from "../chat/attachment.js";

const PAGE_ADDRESS = "#scheduled";
const REFRESH_MS = 10000;
const FILTER_KEY = "scheduledFilter";
/** Other full-page views close themselves when this fires. */
const VIEW_OPENED_EVENT = "main-view-opened";
const WORKER_LABELS = { running: "Running", failing: "Failing", stopped: "Stopped", "not running": "Not running" };
const CLOCK_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>';
const REPEAT_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 2l4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="M7 22l-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/></svg>';

const view = document.getElementById("scheduled-view");
const chatView = document.querySelector(".main");
const openButton = document.getElementById("scheduled-button");
const status = document.getElementById("scheduled-status");
const taskList = document.getElementById("scheduled-tasks-list");
const tasksEmpty = document.getElementById("scheduled-tasks-empty");
const workerList = document.getElementById("scheduled-list");
const workersCount = document.getElementById("scheduled-workers-count");
const filterButton = document.getElementById("scheduled-filter");
const filterLabel = document.getElementById("scheduled-filter-label");
const composer = document.getElementById("scheduled-composer");
const input = document.getElementById("scheduled-input");
const sendButton = document.getElementById("scheduled-send");
const fileInput = document.getElementById("scheduled-file-input");
const fileChips = document.getElementById("scheduled-files");

let refreshTimer = null;
let showAll = readFilter();
let latestTasks = [];
let chosenFiles = [];
/** Tasks whose reactivate time picker is open, so a refresh doesn't close it. */
const reschedulingIds = new Set();

function readFilter() {
  try {
    return localStorage.getItem(FILTER_KEY) === "all";
  } catch {
    return false;
  }
}

function saveFilter() {
  try {
    localStorage.setItem(FILTER_KEY, showAll ? "all" : "active");
  } catch {
    // Only a convenience; the filter still works for this visit.
  }
}

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function showStatus(text) {
  status.textContent = text ?? "";
  status.hidden = !text;
}

async function requestJson(method, url, body) {
  const response = await fetch(url, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(result?.error ?? `Request failed (HTTP ${response.status})`);
    error.body = result;
    throw error;
  }
  return result;
}

function formatDateTime(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  const sameYear = date.getFullYear() === new Date().getFullYear();
  return date.toLocaleString([], {
    weekday: "short",
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
    hour: "numeric",
    minute: "2-digit",
  });
}

function toLocalInputValue(date) {
  const pad = (number) => String(number).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** A plain line about where the task stands, like "Daily · Next run Tue, Nov 11, 6:00 PM". */
function describeTask(task) {
  const meta = createElement("div", "scheduled-task-meta");
  const parts = [task.repeatLabel];
  if (task.isRunning) {
    meta.append(createElement("span", "running", task.approval ? "Waiting for your approval" : "Running now"));
    meta.append(` · ${parts.join(" · ")}`);
    return meta;
  }
  if (task.isActive) {
    parts.push(`Next run ${formatDateTime(task.nextRunAt)}`);
  } else if (task.lastStatus === "completed" && task.repeat === "once") {
    parts.unshift("Completed");
  } else {
    parts.unshift("Off");
  }
  if (task.lastRunAt) parts.push(`Last run ${formatDateTime(task.lastRunAt)}`);
  meta.append(parts.join(" · "));
  if (task.lastStatus === "failed") meta.append(" · ", createElement("span", "failed", "Last run failed"));
  return meta;
}

function actionButton(label, onClick, className = "") {
  const button = createElement("button", `scheduled-action ${className}`.trim(), label);
  button.type = "button";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await onClick();
    } catch (error) {
      showStatus(error.message);
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

async function setActive(task, isActive, runAt) {
  try {
    await requestJson("PATCH", `/api/scheduled/tasks/${task.id}`, { isActive, ...(runAt ? { runAt } : {}) });
    reschedulingIds.delete(task.id);
    showStatus("");
  } catch (error) {
    if (error.body?.needsTime) {
      reschedulingIds.add(task.id);
    } else {
      throw error;
    }
  }
  await refresh();
}

async function deleteTask(task) {
  if (!window.confirm(`Delete "${task.title}"? This can't be undone.`)) return;
  await requestJson("DELETE", `/api/scheduled/tasks/${task.id}`);
  reschedulingIds.delete(task.id);
  showStatus("");
  await refresh();
}

async function openTaskChat(task) {
  closeScheduled();
  if (!(await chatStore.openSavedChat(task.lastConversationId))) {
    openScheduled();
    showStatus("Couldn't open that chat. It may have been deleted.");
  }
}

function renderReschedule(task) {
  const row = createElement("div", "scheduled-reschedule");
  row.append(createElement("span", "", "Run again at"));
  const picker = document.createElement("input");
  picker.type = "datetime-local";
  const suggested = new Date(task.nextRunAt ?? Date.now());
  while (suggested <= new Date()) suggested.setDate(suggested.getDate() + 1);
  picker.value = toLocalInputValue(suggested);
  row.append(picker);
  row.append(
    actionButton(
      "Save",
      async () => {
        const chosen = new Date(picker.value);
        if (Number.isNaN(chosen.getTime()) || chosen <= new Date()) {
          showStatus("Pick a time in the future.");
          return;
        }
        await setActive(task, true, chosen.toISOString());
      },
      "primary",
    ),
  );
  row.append(
    actionButton("Cancel", async () => {
      reschedulingIds.delete(task.id);
      render();
    }),
  );
  return row;
}

function renderApproval(task) {
  const box = createElement("div", "scheduled-approval");
  for (const action of task.approval.actions) {
    box.append(createElement("div", "scheduled-approval-title", action.label));
    const details = Object.entries(action.details ?? {})
      .map(([name, value]) => `${name}: ${typeof value === "string" ? value : JSON.stringify(value)}`)
      .join("\n");
    if (details) box.append(createElement("div", "scheduled-approval-detail", details));
  }
  const buttons = createElement("div", "scheduled-task-actions");
  const answer = (approved) => async () => {
    await requestJson("POST", `/api/chat/approvals/${encodeURIComponent(task.approval.id)}`, { approved });
    await refresh();
  };
  buttons.append(actionButton("Approve", answer(true), "primary"));
  buttons.append(actionButton("Deny", answer(false)));
  box.append(buttons);
  return box;
}

function renderTask(task) {
  const item = createElement("li", `scheduled-task${task.isActive ? "" : " inactive"}`);
  const icon = createElement("span", "scheduled-task-icon");
  icon.innerHTML = task.repeat === "once" ? CLOCK_ICON : REPEAT_ICON;
  item.append(icon);

  const body = createElement("div", "scheduled-task-body");
  body.append(createElement("div", "scheduled-task-title", task.title));
  body.append(describeTask(task));
  body.append(createElement("p", "scheduled-task-instruction", task.instruction));
  if (task.approval) body.append(renderApproval(task));
  if (reschedulingIds.has(task.id)) body.append(renderReschedule(task));
  item.append(body);

  const actions = createElement("div", "scheduled-task-actions");
  if (task.lastConversationId) actions.append(actionButton("Open chat", () => openTaskChat(task)));
  if (task.isActive) {
    actions.append(actionButton("Deactivate", () => setActive(task, false)));
  } else if (!reschedulingIds.has(task.id)) {
    actions.append(actionButton("Reactivate", () => setActive(task, true)));
  }
  actions.append(actionButton("Delete", () => deleteTask(task), "danger"));
  item.append(actions);
  return item;
}

function renderWorker(worker) {
  const item = createElement("li", "scheduled-item");
  const top = createElement("div", "scheduled-item-top");
  top.append(createElement("span", "scheduled-name", worker.name));
  top.append(
    createElement("span", `scheduled-badge ${worker.status.replace(" ", "-")}`, WORKER_LABELS[worker.status] ?? worker.status),
  );
  item.append(top);
  item.append(createElement("p", "scheduled-description", worker.description));
  const times = createElement("div", "scheduled-times");
  times.append(createElement("span", "", everyLabel(worker.everySeconds)));
  times.append(createElement("span", "", `Last run: ${formatDateTime(worker.lastRunAt)}`));
  if (worker.status === "running" || worker.status === "failing") {
    times.append(createElement("span", "", `Next run: ${formatDateTime(worker.nextRunAt)}`));
  }
  item.append(times);
  if (worker.problem) item.append(createElement("p", "scheduled-problem", worker.problem));
  return item;
}

function everyLabel(seconds) {
  if (seconds < 60) return `Every ${Math.round(seconds)} seconds`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return minutes === 1 ? "Every minute" : `Every ${minutes} minutes`;
  const hours = Math.round(minutes / 60);
  return hours === 1 ? "Every hour" : `Every ${hours} hours`;
}

function render() {
  filterLabel.textContent = showAll ? "All" : "Active";
  const shown = showAll ? latestTasks : latestTasks.filter((task) => task.isActive || task.isRunning);
  taskList.replaceChildren(...shown.map(renderTask));
  tasksEmpty.hidden = shown.length > 0;
  tasksEmpty.textContent =
    latestTasks.length > 0 && !showAll
      ? "No active tasks. Switch to All to see past ones."
      : 'No scheduled tasks yet. Try "Text Chris tomorrow at 9am saying I\'m running late."';
}

async function refresh() {
  clearTimeout(refreshTimer);
  try {
    const { tasks, workers } = await requestJson("GET", "/api/scheduled");
    latestTasks = tasks;
    render();
    workerList.replaceChildren(...workers.map(renderWorker));
    workersCount.textContent = workers.length || "";
    if (status.textContent.startsWith("Couldn't load")) showStatus("");
  } catch (error) {
    showStatus(`Couldn't load the schedule: ${error.message}`);
  }
  if (!view.hidden) refreshTimer = setTimeout(refresh, REFRESH_MS);
}

/* ---------- Composer: starts a new chat so the model can ask about anything unclear. ---------- */

function updateComposer() {
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
  sendButton.disabled = !input.value.trim() || chatStore.isBusy();
}

function renderFileChips() {
  fileChips.replaceChildren(
    ...chosenFiles.map((file, index) => {
      const chip = createElement("span", "scheduled-file");
      chip.append(createElement("span", "", file.name));
      const remove = createElement("button", "", "×");
      remove.type = "button";
      remove.setAttribute("aria-label", `Remove ${file.name}`);
      remove.addEventListener("click", () => {
        chosenFiles.splice(index, 1);
        renderFileChips();
      });
      chip.append(remove);
      return chip;
    }),
  );
  fileChips.hidden = chosenFiles.length === 0;
}

async function submitTask(event) {
  event.preventDefault();
  const text = input.value.trim();
  if (!text || chatStore.isBusy()) return;
  const files = chosenFiles;
  input.value = "";
  chosenFiles = [];
  renderFileChips();
  updateComposer();

  closeScheduled();
  await chatStore.createChat();
  if (files.length > 0) await attachUserFiles(files);
  await sendMessage(`Schedule a task: ${text}`);
}

function setupComposer() {
  composer.addEventListener("submit", submitTask);
  input.addEventListener("input", updateComposer);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      composer.requestSubmit();
    }
  });
  fileInput.addEventListener("change", () => {
    chosenFiles = [...chosenFiles, ...fileInput.files];
    fileInput.value = "";
    renderFileChips();
  });
}

/* ---------- Opening and closing ---------- */

function openScheduled() {
  document.dispatchEvent(new CustomEvent(VIEW_OPENED_EVENT, { detail: "scheduled" }));
  chatView.hidden = true;
  view.hidden = false;
  openButton.classList.add("active");
  openButton.setAttribute("aria-pressed", "true");
  history.replaceState(null, "", PAGE_ADDRESS);
  updateComposer();
  refresh();
}

function closeScheduled() {
  clearTimeout(refreshTimer);
  view.hidden = true;
  chatView.hidden = false;
  openButton.classList.remove("active");
  openButton.setAttribute("aria-pressed", "false");
  if (location.hash === PAGE_ADDRESS) history.replaceState(null, "", location.pathname);
}

export function setupScheduled() {
  openButton.setAttribute("aria-pressed", "false");
  openButton.addEventListener("click", () => (view.hidden ? openScheduled() : closeScheduled()));
  filterButton.addEventListener("click", () => {
    showAll = !showAll;
    saveFilter();
    render();
  });
  setupComposer();
  document.getElementById("sidebar").addEventListener("click", (event) => {
    if (!view.hidden && event.target.closest(".chat-title-button, #new-chat-button")) closeScheduled();
  });
  document.addEventListener(VIEW_OPENED_EVENT, (event) => {
    if (event.detail !== "scheduled" && !view.hidden) closeScheduled();
  });
  if (location.hash === PAGE_ADDRESS) openScheduled();
}
