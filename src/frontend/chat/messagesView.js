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
    for (const document of message.documents ?? []) {
      setDocumentCardSaved(addDocumentCard(bubble, document.fileName), document);
    }
  }
}

const copyIconSvg =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="2.5"/><path d="M5 15h-.5A1.5 1.5 0 0 1 3 13.5v-9A1.5 1.5 0 0 1 4.5 3h9A1.5 1.5 0 0 1 15 4.5V5"/></svg>';
const copiedIconSvg =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l5 5L19 7"/></svg>';
const COPIED_ICON_MS = 1500;

function createCopyButton(bubble) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "icon-button message-copy";
  button.setAttribute("aria-label", "Copy");
  button.title = "Copy";
  button.innerHTML = copyIconSvg;
  let resetTimer = null;
  button.addEventListener("click", async () => {
    await navigator.clipboard.writeText(bubble.querySelector(".message-text").textContent);
    button.innerHTML = copiedIconSvg;
    clearTimeout(resetTimer);
    resetTimer = setTimeout(() => { button.innerHTML = copyIconSvg; }, COPIED_ICON_MS);
  });
  return button;
}

// Models mark bold text with ** (Markdown). In replies those parts are shown bold and the stars are hidden.
// Text is only ever set as text, never as HTML, so a reply can't add anything else to the page.
function showText(element, bubble, text) {
  if (!bubble.classList.contains("assistant")) {
    element.textContent = text;
    return;
  }
  const parts = text.split("**");
  // An odd number of ** leaves the last one unclosed (often mid-stream), so what follows it stays plain.
  const closed = parts.length % 2 === 1 ? parts.length : parts.length - 1;
  element.replaceChildren(...parts.map((part, index) => {
    if (index % 2 === 0 || index >= closed) return document.createTextNode(part);
    const bold = document.createElement("strong");
    bold.textContent = part;
    return bold;
  }));
}

export function addMessageBubble(role, text) {
  const bubble = document.createElement("div");
  bubble.className = `message ${role}`;
  const textElement = document.createElement("span");
  textElement.className = "message-text";
  bubble.append(textElement, createCopyButton(bubble));
  showText(textElement, bubble, text);
  messagesContainer.appendChild(bubble);
  scrollToBottom();
  return bubble;
}

/** Changes a bubble's text while keeping its copy button, images and documents. */
export function setBubbleText(bubble, text) {
  showText(bubble.querySelector(".message-text"), bubble, text);
}

export function addImageToBubble(bubble, imageUrl) {
  const image = document.createElement("img");
  image.className = "message-image";
  image.src = imageUrl;
  image.alt = "";
  image.addEventListener("load", scrollToBottom, { once: true });
  bubble.querySelector(".message-copy").before(image);
}

const documentIconSvg =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5"/></svg>';

/** Adds a PDF card to a message bubble. It stays in the "uploading" state until setDocumentCardSaved. */
export function addDocumentCard(bubble, fileName) {
  const card = document.createElement("a");
  card.className = "message-document uploading";
  card.innerHTML = documentIconSvg;
  const name = document.createElement("span");
  name.className = "message-document-name";
  name.textContent = fileName;
  const status = document.createElement("span");
  status.className = "message-document-status";
  status.textContent = "Uploading…";
  card.append(name, status);
  bubble.querySelector(".message-copy").before(card);
  scrollToBottom();
  return card;
}

export function setDocumentCardSaved(card, savedDocument) {
  card.classList.remove("uploading");
  card.href = `/api/documents/${savedDocument.id}`;
  card.target = "_blank";
  card.rel = "noopener";
  card.querySelector(".message-document-status").textContent = `PDF · ${formatSize(savedDocument.sizeBytes)}`;
}

export function setDocumentCardFailed(card) {
  card.classList.remove("uploading");
  card.classList.add("failed");
  card.querySelector(".message-document-status").textContent = "Not saved";
}

function formatSize(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
