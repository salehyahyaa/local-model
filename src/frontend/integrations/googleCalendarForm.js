import * as integrationsApi from "./integrationsApi.js";

const dialog = document.getElementById("google-calendar-dialog");
const form = document.getElementById("google-calendar-form");
const errorText = document.getElementById("google-calendar-form-error");
const cancelButton = document.getElementById("google-calendar-cancel-button");
const continueButton = document.getElementById("google-calendar-continue-button");
const signInRow = document.getElementById("google-calendar-sign-in");
const signInLink = document.getElementById("google-calendar-sign-in-link");

let onConnected = () => {};

function showError(message) {
  errorText.textContent = message;
  errorText.hidden = !message;
}

function showSignIn(authorizationUrl) {
  signInLink.href = authorizationUrl;
  signInRow.hidden = false;
  continueButton.hidden = true;
}

function hideSignIn() {
  signInLink.removeAttribute("href");
  signInRow.hidden = true;
  continueButton.hidden = false;
}

async function handleSubmit(event) {
  event.preventDefault();
  showError("");
  continueButton.disabled = true;
  try {
    const started = await integrationsApi.connectGoogleCalendar({
      clientId: form.elements.clientId.value,
      clientSecret: form.elements.clientSecret.value,
    });
    showSignIn(started.authorizationUrl);
  } catch (error) {
    showError(error.message);
  } finally {
    continueButton.disabled = false;
  }
}

export function openGoogleCalendarForm(handleConnected) {
  onConnected = handleConnected;
  form.reset();
  showError("");
  hideSignIn();
  dialog.showModal();
  form.elements.clientId.focus();
}

export function setupGoogleCalendarForm() {
  form.addEventListener("submit", handleSubmit);
  cancelButton.addEventListener("click", () => dialog.close());
  // The sign-in tab reports back here when it's done, since it's opened without a link to this page.
  new BroadcastChannel("mcp-sign-in").addEventListener("message", () => {
    if (dialog.open) {
      dialog.close();
      onConnected();
    }
  });
}
