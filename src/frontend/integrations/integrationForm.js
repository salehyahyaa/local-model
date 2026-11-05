import * as integrationsApi from "./integrationsApi.js";

const dialog = document.getElementById("integration-dialog");
const form = document.getElementById("integration-form");
const title = document.getElementById("integration-form-title");
const errorText = document.getElementById("integration-form-error");
const cancelButton = document.getElementById("integration-cancel-button");
const saveButton = document.getElementById("integration-save-button");

let onSaved = () => {};

function selectedKind() {
  return form.elements.kind.value;
}

function setSectionVisible(sectionName, isVisible) {
  form.querySelector(`[data-section="${sectionName}"]`).hidden = !isVisible;
}

function updateVisibleSections() {
  const isMcp = selectedKind() === "mcp";
  setSectionVisible("mcp", isMcp);
  setSectionVisible("api", !isMcp);
}

function showError(message) {
  errorText.textContent = message;
  errorText.hidden = !message;
}

function readLines(text) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function parseParameters(text) {
  return readLines(text).map((line) => {
    const required = line.startsWith("*");
    const withoutMarker = required ? line.slice(1) : line;
    const separatorIndex = withoutMarker.indexOf(":");
    if (separatorIndex === -1) {
      return { name: withoutMarker.trim(), description: "", required };
    }
    return {
      name: withoutMarker.slice(0, separatorIndex).trim(),
      description: withoutMarker.slice(separatorIndex + 1).trim(),
      required,
    };
  });
}

function readApiKeyFields() {
  const fields = form.elements;
  if (!fields.apiKey.value.trim()) {
    return { authType: "none" };
  }
  return {
    authType: "apiKey",
    apiKey: fields.apiKey.value,
    authHeader: fields.authHeader.value,
    authPrefix: fields.authPrefix.value,
  };
}

function buildMcpServer() {
  const fields = form.elements;
  return {
    name: fields.name.value,
    transport: "http",
    url: fields.mcpUrl.value,
    authType: "basic",
    username: fields.username.value,
    password: fields.password.value,
  };
}

function buildApiIntegration() {
  const fields = form.elements;
  return {
    name: fields.name.value,
    description: fields.description.value,
    method: fields.method.value,
    url: fields.apiUrl.value,
    parameters: parseParameters(fields.parameters.value),
    ...readApiKeyFields(),
  };
}

async function handleSubmit(event) {
  event.preventDefault();
  showError("");
  saveButton.disabled = true;
  try {
    if (selectedKind() === "mcp") {
      await integrationsApi.addMcpServer(buildMcpServer());
    } else {
      await integrationsApi.addApiIntegration(buildApiIntegration());
    }
    dialog.close();
    onSaved();
  } catch (error) {
    showError(error.message);
  } finally {
    saveButton.disabled = false;
  }
}

export function openIntegrationForm(handleSaved, kind = "mcp") {
  onSaved = handleSaved;
  form.reset();
  form.elements.kind.value = kind;
  title.textContent = kind === "api" ? "Add API" : "Add integration";
  showError("");
  updateVisibleSections();
  dialog.showModal();
  form.elements.name.focus();
}

export function setupIntegrationForm() {
  form.addEventListener("submit", handleSubmit);
  cancelButton.addEventListener("click", () => dialog.close());
}
