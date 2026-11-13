import * as chatStore from "./chatStore.js";
import { hasAttachedDocuments } from "./attachment.js";
import { hasWaitingApproval } from "./approvalCard.js";
import { sendFollowUp, sendMessage } from "./conversation.js";

const messageForm = document.getElementById("message-form");
const composer = document.getElementById("composer");
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");

/** Unsent text per chat, so a draft stays in the chat it was typed in. */
const drafts = new Map();
let draftChatId = null;

function switchDraft() {
  const chatId = chatStore.getActiveChatId();
  if (chatId === draftChatId) return;
  if (messageInput.value) drafts.set(draftChatId, messageInput.value);
  else drafts.delete(draftChatId);
  draftChatId = chatId;
  messageInput.value = drafts.get(chatId) ?? "";
  handleInput();
}

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

function updateSendButton() {
  sendButton.disabled = chatStore.isBusy() && !hasWaitingApproval();
}

async function submitFollowUp(text) {
  messageInput.value = "";
  handleInput();
  try {
    await sendFollowUp(text);
  } catch {
    // The card shows what went wrong. The owner's words go back in the box so they aren't lost.
    messageInput.value = text;
    handleInput();
  }
}

async function handleSubmit(event) {
  event.preventDefault();
  const text = messageInput.value.trim();
  if (chatStore.isBusy()) {
    if (text && hasWaitingApproval()) await submitFollowUp(text);
    return;
  }
  if (!text && !hasAttachedDocuments()) return;

  if (text === "/clear") {
    messageInput.value = "";
    handleInput();
    chatStore.clearActiveChat();
    return;
  }

  messageInput.value = "";
  handleInput();
  sendButton.disabled = true;
  await sendMessage(text);
  updateSendButton();
  focusInput();
}

export function setupComposer() {
  draftChatId = chatStore.getActiveChatId();
  chatStore.subscribe("activeChatChanged", switchDraft);
  document.addEventListener("approval-wait-changed", updateSendButton);
  messageForm.addEventListener("submit", handleSubmit);
  messageInput.addEventListener("input", handleInput);
  messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      messageForm.requestSubmit();
    }
  });
}
