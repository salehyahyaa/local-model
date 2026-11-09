import * as integrationsApi from "./integrationsApi.js";
import { openIntegrationForm } from "./integrationForm.js";
import { openGmailForm } from "./gmailForm.js";
import { openGoogleCalendarForm } from "./googleCalendarForm.js";
import { openPhoneCallsForm } from "./phoneCallsForm.js";
import { attachUserFiles } from "../chat/attachment.js";
import { createLogo } from "./logos.js";

const addButton = document.getElementById("add-button");
const menu = document.getElementById("integrations-menu");
const list = document.getElementById("integrations-list");
const message = document.getElementById("integrations-message");
const addIntegrationButton = document.getElementById("add-integration-button");
const addApiButton = document.getElementById("add-api-button");
const addGoogleCalendarButton = document.getElementById("add-google-calendar-button");
const addPhoneCallsButton = document.getElementById("add-phone-calls-button");
const TARGET_PREFIXES = { mcp: "MCP", api: "API", phone: "Calling for" };

let gmailConnected = false;
// Only the newest refresh may draw, so a slow check can't mark rows from an older list.
let latestRefresh = 0;
const addFilesButton = document.getElementById("add-files-button");
const addFilesInput = document.getElementById("add-files-input");

const removeIconSvg =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>';

function showMessage(text) {
  message.textContent = text;
  message.hidden = !text;
}

function createToggle(integration) {
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "toggle-switch";
  toggle.classList.toggle("on", integration.enabled);
  toggle.title = integration.enabled ? "Turn off" : "Turn on";
  toggle.setAttribute("role", "switch");
  toggle.setAttribute("aria-checked", String(integration.enabled));
  toggle.addEventListener("click", async () => {
    try {
      await integrationsApi.setIntegrationEnabled(integration.kind, integration.id, !integration.enabled);
      await refreshList();
    } catch (error) {
      showMessage(error.message);
    }
  });
  return toggle;
}

function createRemoveButton(integration) {
  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.className = "integration-remove-button";
  removeButton.title = "Remove";
  removeButton.innerHTML = removeIconSvg;
  removeButton.addEventListener("click", async () => {
    try {
      await integrationsApi.removeIntegration(integration.kind, integration.id);
      await refreshList();
    } catch (error) {
      showMessage(error.message);
    }
  });
  return removeButton;
}

function createGmailDetails(integration) {
  const details = document.createElement("div");
  details.className = "integration-details";
  const address = document.createElement("div");
  address.className = "integration-name";
  address.textContent = integration.target;
  address.title = integration.target;
  details.append(address);
  return details;
}

function createDetails(integration) {
  const details = document.createElement("div");
  details.className = "integration-details";
  const name = document.createElement("div");
  name.className = "integration-name";
  name.textContent = integration.name;
  const target = document.createElement("div");
  target.className = "integration-target";
  target.textContent = `${TARGET_PREFIXES[integration.kind]} · ${integration.target}`;
  target.title = integration.target;
  details.append(name, target);
  return details;
}

function createIntegrationItem(integration) {
  const item = document.createElement("div");
  item.className = "integration-item";
  const details = integration.provider === "gmail" ? createGmailDetails(integration) : createDetails(integration);
  item.append(createLogo(integration), details, createToggle(integration), createRemoveButton(integration));
  item.dataset.integrationKey = integrationKey(integration);
  return item;
}

function integrationKey(integration) {
  return `${integration.kind}:${integration.id}`;
}

function showProblem(item, problem) {
  const status = document.createElement("div");
  status.className = "integration-problem";
  status.textContent = `Disconnected · ${problem}`;
  status.title = problem;
  item.querySelector(".integration-details").appendChild(status);
}

async function showBrokenConnections(refresh) {
  let health;
  try {
    health = await integrationsApi.checkIntegrationHealth();
  } catch {
    // The list is still useful without its status, and any real error already shows when the list loads.
    return;
  }
  if (refresh !== latestRefresh) {
    return;
  }
  for (const integration of health.integrations) {
    const item = list.querySelector(`[data-integration-key="${integrationKey(integration)}"]`);
    if (item && integration.problem) {
      showProblem(item, integration.problem);
    }
  }
}

async function refreshList() {
  latestRefresh += 1;
  const refresh = latestRefresh;
  list.innerHTML = "";
  showMessage("");
  let integrations;
  try {
    integrations = await integrationsApi.listIntegrations();
  } catch (error) {
    showMessage(error.message);
    return;
  }
  const allIntegrations = [...integrations.mcpServers, ...integrations.apiIntegrations, ...integrations.phoneCalls];
  gmailConnected = allIntegrations.some((integration) => integration.provider === "gmail");
  addGoogleCalendarButton.hidden = allIntegrations.some((integration) => integration.provider === "google-calendar");
  addPhoneCallsButton.hidden = integrations.phoneCalls.length > 0;
  if (refresh !== latestRefresh) {
    return;
  }
  for (const integration of allIntegrations) {
    list.appendChild(createIntegrationItem(integration));
  }
  showBrokenConnections(refresh);
}

function openMenu() {
  const buttonPosition = addButton.getBoundingClientRect();
  menu.style.left = `${buttonPosition.left}px`;
  menu.style.top = "auto";
  menu.style.bottom = `${window.innerHeight - buttonPosition.top + 8}px`;
  menu.hidden = false;
  refreshList();
}

function closeMenu() {
  menu.hidden = true;
}

export function setupIntegrationsMenu() {
  addButton.addEventListener("click", (event) => {
    event.stopPropagation();
    if (menu.hidden) {
      openMenu();
    } else {
      closeMenu();
    }
  });

  addFilesButton.addEventListener("click", () => {
    closeMenu();
    addFilesInput.click();
  });
  addFilesInput.addEventListener("change", async () => {
    await attachUserFiles([...addFilesInput.files]);
    addFilesInput.value = "";
  });

  addIntegrationButton.addEventListener("click", () => {
    closeMenu();
    if (gmailConnected) {
      openIntegrationForm(openMenu);
    } else {
      openGmailForm(openMenu, () => openIntegrationForm(openMenu));
    }
  });

  addApiButton.addEventListener("click", () => {
    closeMenu();
    openIntegrationForm(openMenu, "api");
  });

  addGoogleCalendarButton.addEventListener("click", () => {
    closeMenu();
    openGoogleCalendarForm(openMenu);
  });

  addPhoneCallsButton.addEventListener("click", () => {
    closeMenu();
    openPhoneCallsForm(openMenu);
  });

  document.addEventListener("click", (event) => {
    if (!menu.hidden && !menu.contains(event.target)) {
      closeMenu();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeMenu();
    }
  });
}
