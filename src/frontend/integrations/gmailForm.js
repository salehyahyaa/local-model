import * as integrationsApi from "./integrationsApi.js";

const dialog = document.getElementById("gmail-dialog");
const form = document.getElementById("gmail-form");
const errorText = document.getElementById("gmail-form-error");
const cancelButton = document.getElementById("gmail-cancel-button");
const connectButton = document.getElementById("gmail-connect-button");

const otherButton = document.getElementById("gmail-other-button");

let onConnected = () => {};
let onChooseOther = () => {};

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
    await integrationsApi.connectGmail({
      address: form.elements.address.value,
      appPassword: form.elements.appPassword.value,
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

export function openGmailForm(handleConnected, handleChooseOther) {
  onConnected = handleConnected;
  onChooseOther = handleChooseOther;
  form.reset();
  showError("");
  dialog.showModal();
  form.elements.address.focus();
}

export function setupGmailForm() {
  form.addEventListener("submit", handleSubmit);
  cancelButton.addEventListener("click", () => dialog.close());
  otherButton.addEventListener("click", () => {
    dialog.close();
    onChooseOther();
  });
}
