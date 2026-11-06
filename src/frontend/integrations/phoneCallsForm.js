import * as integrationsApi from "./integrationsApi.js";

const dialog = document.getElementById("phone-calls-dialog");
const form = document.getElementById("phone-calls-form");
const errorText = document.getElementById("phone-calls-form-error");
const cancelButton = document.getElementById("phone-calls-cancel-button");
const connectButton = document.getElementById("phone-calls-connect-button");

let onConnected = () => {};

function showError(message) {
  errorText.textContent = message;
  errorText.hidden = !message;
}

function setConnecting(isConnecting) {
  connectButton.disabled = isConnecting;
  connectButton.textContent = isConnecting ? "Connecting…" : "Connect";
}

async function handleSubmit(event) {
  event.preventDefault();
  showError("");
  setConnecting(true);
  try {
    await integrationsApi.connectPhoneCalls({
      ownerName: form.elements.ownerName.value,
      apiKey: form.elements.apiKey.value,
      agentId: form.elements.agentId.value,
      phoneNumberId: form.elements.phoneNumberId.value,
    });
    form.reset();
    dialog.close();
    onConnected();
  } catch (error) {
    showError(error.message);
  } finally {
    setConnecting(false);
  }
}

export function openPhoneCallsForm(handleConnected) {
  onConnected = handleConnected;
  form.reset();
  showError("");
  dialog.showModal();
  form.elements.ownerName.focus();
}

export function setupPhoneCallsForm() {
  form.addEventListener("submit", handleSubmit);
  cancelButton.addEventListener("click", () => dialog.close());
}
