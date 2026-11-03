import * as chatStore from "./chatStore.js";

const messagesScroll = document.getElementById("messages-scroll");
const messagesContainer = document.getElementById("messages");

export function renderMessages() {
  messagesContainer.innerHTML = "";
  for (const message of chatStore.getActiveChat().messages) {
    addMessageBubble(message.role, message.content);
  }
}

export function addMessageBubble(role, text) {
  const bubble = document.createElement("div");
  bubble.className = `message ${role}`;
  bubble.textContent = text;
  messagesContainer.appendChild(bubble);
  scrollToBottom();
  return bubble;
}

export function scrollToBottom() {
  messagesScroll.scrollTop = messagesScroll.scrollHeight;
}
