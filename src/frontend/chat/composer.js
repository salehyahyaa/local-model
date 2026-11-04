import * as chatStore from "./chatStore.js";
import { hasAttachedDocuments } from "./attachment.js";
import { sendMessage } from "./conversation.js";

const messageForm = document.getElementById("message-form");
const composer = document.getElementById("composer");
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");

function resizeInput() {
  messageInput.style.height = "auto";
  messageInput.style.height = `${messageInput.scrollHeight}px`;
}

function updateButtons() {
  composer.classList.toggle("has-text", messageInput.value.trim().length > 0);
}

function handleInput() {
  resizeInput();
  updateButtons();
}

export function setVoiceActive(isActive) {
  composer.classList.toggle("voice-active", isActive);
}

export function focusInput() {
  messageInput.focus();
}

async function handleSubmit(event) {
  event.preventDefault();
  const text = messageInput.value.trim();
  if ((!text && !hasAttachedDocuments()) || chatStore.isBusy()) return;

  messageInput.value = "";
  handleInput();
  sendButton.disabled = true;
  await sendMessage(text);
  sendButton.disabled = false;
  focusInput();
}

export function setupComposer() {
  messageForm.addEventListener("submit", handleSubmit);
  messageInput.addEventListener("input", handleInput);
  messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      messageForm.requestSubmit();
    }
  });
}
