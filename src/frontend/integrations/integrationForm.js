import * as integrationsApi from "./integrationsApi.js";

const dialog = document.getElementById("integration-dialog");
const form = document.getElementById("integration-form");
const title = document.getElementById("integration-form-title");
const errorText = document.getElementById("integration-form-error");
const cancelButton = document.getElementById("integration-cancel-button");
const saveButton = document.getElementById("integration-save-button");
const signInRow = document.getElementById("integration-sign-in");
const signInLink = document.getElementById("integration-sign-in-link");
const redirectAddress = document.getElementById("mcp-redirect-address");

let onSaved = () => {};

function selectedKind() {
  return form.elements.kind.value;
}

function setSectionVisible(sectionName, isVisible) {
  form.querySelector(`[data-section="${sectionName}"]`).hidden = !isVisible;
}

function updateVisibleSections() {
  const isMcp = selectedKind() === "mcp";
  const isLocal = form.elements.mcpTransport.value === "stdio";
  const login = form.elements.mcpAuth.value;
  setSectionVisible("mcp", isMcp);
  setSectionVisible("api", !isMcp);
  setSectionVisible("mcp-http", !isLocal);
  setSectionVisible("mcp-stdio", isLocal);
  setSectionVisible("mcp-oauth", login === "oauth");
  setSectionVisible("mcp-api-key", login === "apiKey");
  setSectionVisible("mcp-basic", login === "basic");
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

function parseEnvironment(text) {
  return readLines(text).map((line) => {
    const separatorIndex = line.indexOf("=");
    if (separatorIndex === -1) {
      return { name: line, value: "" };
    }
    return { name: line.slice(0, separatorIndex).trim(), value: line.slice(separatorIndex + 1).trim() };
  });
}

function buildMcpLogin() {
  const fields = form.elements;
  const authType = fields.mcpAuth.value;
  if (authType === "oauth") {
    return { authType, clientId: fields.clientId.value, clientSecret: fields.clientSecret.value };
  }
  if (authType === "apiKey") {
    return {
      authType,
      apiKey: fields.mcpApiKey.value,
      authHeader: fields.mcpAuthHeader.value,
      authPrefix: fields.mcpAuthPrefix.value,
    };
  }
  if (authType === "basic") {
    return { authType, username: fields.username.value, password: fields.password.value };
  }
  return { authType };
}

function buildMcpServer() {
  const fields = form.elements;
  if (fields.mcpTransport.value === "stdio") {
    return {
      name: fields.name.value,
      transport: "stdio",
      command: fields.mcpCommand.value,
      env: parseEnvironment(fields.mcpEnv.value),
    };
  }
  return { name: fields.name.value, transport: "http", url: fields.mcpUrl.value, ...buildMcpLogin() };
}

function showSignIn(authorizationUrl) {
  signInLink.href = authorizationUrl;
  signInRow.hidden = false;
  saveButton.hidden = true;
}

function hideSignIn() {
  signInLink.removeAttribute("href");
  signInRow.hidden = true;
  saveButton.hidden = false;
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
      const added = await integrationsApi.addMcpServer(buildMcpServer());
      if (added.authorizationUrl) {
        showSignIn(added.authorizationUrl);
        return;
      }
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
  hideSignIn();
  updateVisibleSections();
  dialog.showModal();
  form.elements.name.focus();
}

export function setupIntegrationForm() {
  form.addEventListener("submit", handleSubmit);
  form.elements.mcpTransport.addEventListener("change", updateVisibleSections);
  form.elements.mcpAuth.addEventListener("change", updateVisibleSections);
  cancelButton.addEventListener("click", () => dialog.close());
  redirectAddress.textContent = `${location.origin}/api/integrations/mcp/oauth/callback`;
  // The sign-in tab reports back here when it's done, since it's opened without a link to this page.
  new BroadcastChannel("mcp-sign-in").addEventListener("message", () => {
    if (dialog.open) {
      dialog.close();
      onSaved();
    }
  });
}
