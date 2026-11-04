import * as integrationsApi from "./integrationsApi.js";
import { openIntegrationForm } from "./integrationForm.js";
import { attachImageFiles } from "../models/modelPicker.js";

const addButton = document.getElementById("add-button");
const menu = document.getElementById("integrations-menu");
const list = document.getElementById("integrations-list");
const message = document.getElementById("integrations-message");
const addIntegrationButton = document.getElementById("add-integration-button");
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

function createIntegrationItem(integration) {
  const item = document.createElement("div");
  item.className = "integration-item";

  const details = document.createElement("div");
  details.className = "integration-details";
  const name = document.createElement("div");
  name.className = "integration-name";
  name.textContent = integration.name;
  const target = document.createElement("div");
  target.className = "integration-target";
  target.textContent = integration.kind === "mcp" ? `MCP · ${integration.target}` : `API · ${integration.target}`;
  target.title = integration.target;
  details.append(name, target);

  item.append(details, createToggle(integration), createRemoveButton(integration));
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
  const allIntegrations = [...integrations.mcpServers, ...integrations.apiIntegrations];
  if (allIntegrations.length === 0) {
    showMessage("No integrations yet.");
  }
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
    await attachImageFiles([...addFilesInput.files]);
    addFilesInput.value = "";
  });

  addIntegrationButton.addEventListener("click", () => {
    closeMenu();
    openIntegrationForm(openMenu);
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
