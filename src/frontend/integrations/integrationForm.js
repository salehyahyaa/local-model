import * as integrationsApi from "./integrationsApi.js";

const dialog = document.getElementById("integration-dialog");
const form = document.getElementById("integration-form");
const errorText = document.getElementById("integration-form-error");
const cancelButton = document.getElementById("integration-cancel-button");
const saveButton = document.getElementById("integration-save-button");

let onSaved = () => {};

function selectedKind() {
  return form.elements.kind.value;
}

function selectedTransport() {
  return form.elements.transport.value;
}

function setSectionVisible(sectionName, isVisible) {
  form.querySelector(`[data-section="${sectionName}"]`).hidden = !isVisible;
}

function updateVisibleSections() {
  const isMcp = selectedKind() === "mcp";
  const isHttp = selectedTransport() === "http";
  setSectionVisible("mcp", isMcp);
  setSectionVisible("mcp-http", isMcp && isHttp);
  setSectionVisible("mcp-stdio", isMcp && !isHttp);
  setSectionVisible("api", !isMcp);
  setSectionVisible("auth", !isMcp || isHttp);
  const authType = form.elements.authType.value;
  setSectionVisible("auth-basic", authType === "basic");
  setSectionVisible("auth-api-key", authType === "apiKey");
  setSectionVisible("auth-api-key-header", authType === "apiKey");
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

function parseEnvironment(text) {
  return readLines(text).map((line) => {
    const separatorIndex = line.indexOf("=");
    if (separatorIndex === -1) {
      return { name: line, value: "" };
    }
    return { name: line.slice(0, separatorIndex).trim(), value: line.slice(separatorIndex + 1).trim() };
  });
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

function readAuthFields() {
  const fields = form.elements;
  const authType = fields.authType.value;
  if (authType === "basic") {
    return { authType, username: fields.username.value, password: fields.password.value };
  }
  if (authType === "apiKey") {
    return { authType, apiKey: fields.apiKey.value, authHeader: fields.authHeader.value, authPrefix: fields.authPrefix.value };
  }
  return { authType };
}

function buildMcpServer() {
  const fields = form.elements;
  if (selectedTransport() === "http") {
    return { name: fields.name.value, transport: "http", url: fields.mcpUrl.value, ...readAuthFields() };
  }
  return {
    name: fields.name.value,
    transport: "stdio",
    command: fields.command.value,
    args: fields.args.value,
    env: parseEnvironment(fields.env.value),
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
    ...readAuthFields(),
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

export function openIntegrationForm(handleSaved) {
  onSaved = handleSaved;
  form.reset();
  showError("");
  updateVisibleSections();
  dialog.showModal();
  form.elements.name.focus();
}

export function setupIntegrationForm() {
  form.addEventListener("change", updateVisibleSections);
  form.addEventListener("submit", handleSubmit);
  cancelButton.addEventListener("click", () => dialog.close());
}
