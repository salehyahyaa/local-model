import * as integrationsApi from "./integrationsApi.js";
import { openIntegrationForm } from "./integrationForm.js";
import { openGmailForm } from "./gmailForm.js";
import { openPhoneCallsForm } from "./phoneCallsForm.js";
import { attachUserFiles } from "../chat/attachment.js";

const addButton = document.getElementById("add-button");
const menu = document.getElementById("integrations-menu");
const list = document.getElementById("integrations-list");
const message = document.getElementById("integrations-message");
const addIntegrationButton = document.getElementById("add-integration-button");
const addApiButton = document.getElementById("add-api-button");
const addPhoneCallsButton = document.getElementById("add-phone-calls-button");
const TARGET_PREFIXES = { mcp: "MCP", api: "API", phone: "Calling for" };

let gmailConnected = false;
const addFilesButton = document.getElementById("add-files-button");
const addFilesInput = document.getElementById("add-files-input");

const removeIconSvg =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>';

const gmailLogoSvg =
  '<svg viewBox="0 0 48 48" width="16" height="16" aria-label="Gmail" role="img"><path fill="#4caf50" d="M45 16.2l-5 2.75-5 4.75V40h7c1.657 0 3-1.343 3-3V16.2z"/><path fill="#1e88e5" d="M3 16.2l3.614 1.71L13 23.7V40H6c-1.657 0-3-1.343-3-3V16.2z"/><polygon fill="#e53935" points="35,11.2 24,19.45 13,11.2 12,17 13,23.7 24,31.95 35,23.7 36,17"/><path fill="#c62828" d="M3 12.298V16.2l10 7.5V11.2L9.876 8.859C9.132 8.301 8.228 8 7.298 8 4.924 8 3 9.924 3 12.298z"/><path fill="#fbc02d" d="M45 12.298V16.2l-10 7.5V11.2l3.124-2.341C38.868 8.301 39.772 8 40.702 8 43.076 8 45 9.924 45 12.298z"/></svg>';

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
  const logo = document.createElement("span");
  logo.className = "integration-logo";
  logo.title = "Gmail";
  logo.innerHTML = gmailLogoSvg;

  const details = document.createElement("div");
  details.className = "integration-details";
  const address = document.createElement("div");
  address.className = "integration-name";
  address.textContent = integration.target;
  address.title = integration.target;
  details.append(address);
  return [logo, details];
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
  return [details];
}

function createIntegrationItem(integration) {
  const item = document.createElement("div");
  item.className = "integration-item";
  const details = integration.provider === "gmail" ? createGmailDetails(integration) : createDetails(integration);
  item.append(...details, createToggle(integration), createRemoveButton(integration));
  return item;
}

async function refreshList() {
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
  addPhoneCallsButton.hidden = integrations.phoneCalls.length > 0;
  for (const integration of allIntegrations) {
    list.appendChild(createIntegrationItem(integration));
  }
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
