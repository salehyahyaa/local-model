import * as chatStore from "./chatStore.js";

const messagesScroll = document.getElementById("messages-scroll");
const messagesContainer = document.getElementById("messages");

export function renderMessages() {
  messagesContainer.innerHTML = "";
  for (const message of chatStore.getActiveChat().messages) {
    const bubble = addMessageBubble(message.role, message.content);
    for (const imageFile of message.imageFiles ?? []) {
      addImageToBubble(bubble, `/api/images/${imageFile}`);
    }
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

export function addImageToBubble(bubble, imageUrl) {
  const image = document.createElement("img");
  image.className = "message-image";
  image.src = imageUrl;
  image.alt = "";
  image.addEventListener("load", scrollToBottom, { once: true });
  bubble.appendChild(image);
}

export function addToolNote(label, beforeElement) {
  const note = document.createElement("div");
  note.className = "tool-note";
  note.textContent = `Used ${label}`;
  messagesContainer.insertBefore(note, beforeElement);
  scrollToBottom();
}

export function scrollToBottom() {
  messagesScroll.scrollTop = messagesScroll.scrollHeight;
}
