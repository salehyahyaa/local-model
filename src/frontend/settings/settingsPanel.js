import { requestJson } from "../shared/httpClient.js";

const openButton = document.getElementById("settings-button");
const dialog = document.getElementById("settings-dialog");
const form = document.getElementById("settings-form");
const promptInput = document.getElementById("system-prompt-input");
const errorText = document.getElementById("settings-error");
const statusText = document.getElementById("settings-status");
const resetButton = document.getElementById("system-prompt-reset-button");
const saveButton = document.getElementById("system-prompt-save-button");
const closeButton = document.getElementById("settings-close-button");
const integrationsList = document.getElementById("settings-integrations");
const servicesList = document.getElementById("settings-services");

function showError(message) {
  errorText.textContent = message;
  errorText.hidden = !message;
}

function createItem(connection) {
  const item = document.createElement("div");
  item.className = "settings-item";
  const dot = document.createElement("span");
  dot.className = "settings-item-dot";
  dot.classList.toggle("on", connection.isConnected);
  const details = document.createElement("div");
  details.className = "settings-item-details";
  const name = document.createElement("div");
  name.textContent = connection.name;
  const detail = document.createElement("div");
  detail.className = "settings-item-detail";
  detail.textContent = connection.detail;
  details.append(name, detail);
  item.append(dot, details);
  return item;
}

function renderList(list, connections, emptyText) {
  if (connections.length > 0) {
    list.replaceChildren(...connections.map(createItem));
    return;
  }
  const empty = document.createElement("div");
  empty.className = "settings-empty";
  empty.textContent = emptyText;
  list.replaceChildren(empty);
}

async function savePrompt(systemPrompt, savedMessage) {
  showError("");
  statusText.textContent = "";
  saveButton.disabled = true;
  resetButton.disabled = true;
  try {
    const saved = await requestJson("PUT", "/api/system-prompt", { systemPrompt });
    promptInput.value = saved.systemPrompt;
    statusText.textContent = savedMessage;
  } catch (error) {
    showError(error.message);
  } finally {
    saveButton.disabled = false;
    resetButton.disabled = false;
  }
}

async function loadPrompt() {
  try {
    promptInput.value = (await requestJson("GET", "/api/system-prompt")).systemPrompt;
  } catch (error) {
    showError(error.message);
  }
}

async function loadConnections() {
  try {
    const { services, integrations } = await requestJson("GET", "/api/connections");
    renderList(integrationsList, integrations, "None yet. Add one from the + button.");
    renderList(servicesList, services, "Nothing connected.");
  } catch (error) {
    showError(error.message);
  }
}

function openSettings() {
  showError("");
  statusText.textContent = "";
  promptInput.value = "";
  integrationsList.replaceChildren();
  servicesList.replaceChildren();
  dialog.showModal();
  loadPrompt();
  loadConnections();
}

export function setupSettingsPanel() {
  openButton.addEventListener("click", openSettings);
  closeButton.addEventListener("click", () => dialog.close());
  resetButton.addEventListener("click", () => savePrompt(null, "Default restored"));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    savePrompt(promptInput.value, "Saved");
  });
}
