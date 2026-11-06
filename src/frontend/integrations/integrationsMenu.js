import * as integrationsApi from "./integrationsApi.js";
import { openIntegrationForm } from "./integrationForm.js";
import { openGmailForm } from "./gmailForm.js";
import { openGoogleCalendarForm } from "./googleCalendarForm.js";
import { openPhoneCallsForm } from "./phoneCallsForm.js";
import { attachUserFiles } from "../chat/attachment.js";

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

const gmailLogoSvg =
  '<svg viewBox="0 0 48 48" width="16" height="16" aria-label="Gmail" role="img"><path fill="#4caf50" d="M45 16.2l-5 2.75-5 4.75V40h7c1.657 0 3-1.343 3-3V16.2z"/><path fill="#1e88e5" d="M3 16.2l3.614 1.71L13 23.7V40H6c-1.657 0-3-1.343-3-3V16.2z"/><polygon fill="#e53935" points="35,11.2 24,19.45 13,11.2 12,17 13,23.7 24,31.95 35,23.7 36,17"/><path fill="#c62828" d="M3 12.298V16.2l10 7.5V11.2L9.876 8.859C9.132 8.301 8.228 8 7.298 8 4.924 8 3 9.924 3 12.298z"/><path fill="#fbc02d" d="M45 12.298V16.2l-10 7.5V11.2l3.124-2.341C38.868 8.301 39.772 8 40.702 8 43.076 8 45 9.924 45 12.298z"/></svg>';

const googleCalendarLogoSvg =
  '<svg viewBox="0 0 48 48" width="16" height="16" aria-label="Google Calendar" role="img"><rect width="22" height="22" x="13" y="13" fill="#fff"/><polygon fill="#1e88e5" points="25.68,20.92 26.688,22.36 28.272,21.208 28.272,29.56 30,29.56 30,18.616 28.56,18.616"/><path fill="#1e88e5" d="M22.943,23.745c0.625-0.574,1.013-1.37,1.013-2.249c0-1.747-1.533-3.168-3.417-3.168c-1.602,0-2.972,1.009-3.33,2.453l1.657,0.421c0.165-0.664,0.868-1.146,1.673-1.146c0.942,0,1.709,0.646,1.709,1.44c0,0.794-0.767,1.44-1.709,1.44h-0.997v1.728h0.997c1.081,0,1.993,0.751,1.993,1.64c0,0.904-0.866,1.64-1.931,1.64c-0.962,0-1.784-0.61-1.914-1.418L17,26.802c0.262,1.636,1.81,2.87,3.6,2.87c2.007,0,3.64-1.511,3.64-3.368C24.24,25.281,23.736,24.363,22.943,23.745z"/><polygon fill="#fbc02d" points="34,42 14,42 13,38 14,34 34,34 35,38"/><polygon fill="#4caf50" points="38,35 42,34 42,14 38,13 34,14 34,34"/><path fill="#1e88e5" d="M34,14l1-4l-1-4H9C7.343,6,6,7.343,6,9v25l4,1l4-1V14H34z"/><polygon fill="#e53935" points="34,34 34,42 42,34"/><path fill="#1565c0" d="M39,6h-5v8h8V9C42,7.343,40.657,6,39,6z"/><path fill="#1565c0" d="M9,42h5v-8H6v5C6,40.657,7.343,42,9,42z"/></svg>';

const phoneLogoSvg =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-label="Phone calls" role="img"><path d="M21 16.5v3a2 2 0 0 1-2.2 2A18 18 0 0 1 2.5 5.2 2 2 0 0 1 4.5 3h3a2 2 0 0 1 2 1.7l.4 2.6a2 2 0 0 1-.6 1.8L8 10.4a15 15 0 0 0 5.6 5.6l1.3-1.3a2 2 0 0 1 1.8-.6l2.6.4a2 2 0 0 1 1.7 2Z"/></svg>';

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

function builtInLogo(integration) {
  if (integration.provider === "gmail") {
    return gmailLogoSvg;
  }
  if (integration.provider === "google-calendar") {
    return googleCalendarLogoSvg;
  }
  return integration.kind === "phone" ? phoneLogoSvg : null;
}

function siteIconUrl(target) {
  try {
    const { protocol, origin } = new URL(target);
    return protocol === "http:" || protocol === "https:" ? `${origin}/favicon.ico` : null;
  } catch {
    return null;
  }
}

function createLetterLogo(logo, integration) {
  logo.classList.add("integration-logo-letter");
  logo.textContent = Array.from(integration.name.trim())[0]?.toUpperCase() ?? "?";

  const iconUrl = siteIconUrl(integration.target);
  if (!iconUrl) {
    return;
  }
  // The letter stays until the service's own icon loads, and stays for good if it has none.
  const icon = new Image(16, 16);
  icon.alt = "";
  icon.referrerPolicy = "no-referrer";
  icon.addEventListener("load", () => {
    logo.classList.remove("integration-logo-letter");
    logo.replaceChildren(icon);
  });
  icon.src = iconUrl;
}

function createLogo(integration) {
  const logo = document.createElement("span");
  logo.className = "integration-logo";
  logo.title = integration.name;
  const svg = builtInLogo(integration);
  if (svg) {
    logo.innerHTML = svg;
  } else {
    createLetterLogo(logo, integration);
  }
  return logo;
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
