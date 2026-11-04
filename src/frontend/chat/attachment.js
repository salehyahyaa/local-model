import { addMessageBubble } from "./messagesView.js";

const BASE_URL = "/assets/chat";
const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"];
const PDF_TYPE = "application/pdf";
const MAX_IMAGES = 20;
const MAX_FILE_BYTES = 20 * 1024 * 1024;
const MAX_TOTAL_BYTES = 100 * 1024 * 1024;

const removeIconSvg =
  '<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>';

let attachedFiles = [];
let controlsReady = null;
let isDropOverlayVisible = false;

function isPdf(file) {
  return file.type === PDF_TYPE || (!file.type && file.name.toLowerCase().endsWith(".pdf"));
}

function isImage(file) {
  return IMAGE_TYPES.includes(file.type);
}

const documentIconSvg =
  '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5"/></svg>';

function createDocumentPreview(file) {
  const card = document.createElement("div");
  card.className = "document-preview";
  card.innerHTML = documentIconSvg;
  const name = document.createElement("span");
  name.textContent = file.name;
  card.appendChild(name);
  return card;
}

function totalBytes(files) {
  return files.reduce((total, file) => total + file.size, 0);
}

function createThumbnail(file) {
  const frame = document.createElement("div");
  frame.className = "image-preview-frame";

  let content;
  if (isPdf(file)) {
    frame.classList.add("document");
    content = createDocumentPreview(file);
  } else {
    content = document.createElement("img");
    content.src = URL.createObjectURL(file);
    content.alt = file.name;
    content.addEventListener("load", () => URL.revokeObjectURL(content.src), { once: true });
  }

  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.className = "image-preview-remove";
  removeButton.title = "Remove";
  removeButton.innerHTML = removeIconSvg;
  removeButton.addEventListener("click", () => {
    attachedFiles = attachedFiles.filter((attached) => attached !== file);
    renderPreview();
  });

  frame.append(content, removeButton);
  return frame;
}

function renderPreview() {
  const preview = document.getElementById("image-preview");
  preview.replaceChildren(...attachedFiles.map(createThumbnail));
  preview.hidden = attachedFiles.length === 0;
}

function usableFiles(files) {
  const usable = files.filter((file) => (isImage(file) || isPdf(file)) && file.size <= MAX_FILE_BYTES);
  if (usable.length < files.length) {
    addMessageBubble("assistant", "Only PNG, JPEG or WebP images and PDFs up to 20 MB can be added, so some were skipped.");
  }
  return usable;
}

async function attachFiles(files) {
  await loadControlsOnce();
  const skippedForCount = attachedFiles.length + files.length > MAX_IMAGES;
  let skippedForSize = false;
  for (const file of files.slice(0, Math.max(0, MAX_IMAGES - attachedFiles.length))) {
    if (totalBytes(attachedFiles) + file.size > MAX_TOTAL_BYTES) {
      skippedForSize = true;
    } else {
      attachedFiles.push(file);
    }
  }
  renderPreview();
  if (skippedForCount) {
    addMessageBubble("assistant", `You can send up to ${MAX_IMAGES} files in a message, so some weren't added.`);
  }
  if (skippedForSize) {
    addMessageBubble("assistant", "A message's files can total up to 100 MB, so some weren't added.");
  }
}

/** Adds the usable images and PDFs from dropped or chosen files to the next message. */
export async function attachUserFiles(files) {
  const usable = usableFiles(files);
  if (usable.length > 0) {
    await attachFiles(usable);
    document.getElementById("message-input").focus();
  }
}

// This HTML and CSS only load once they're first needed.
async function loadControls() {
  const stylesheet = document.createElement("link");
  stylesheet.rel = "stylesheet";
  stylesheet.href = `${BASE_URL}/attachment.css`;
  document.head.appendChild(stylesheet);

  const response = await fetch(`${BASE_URL}/attachment.html`);
  const template = document.createElement("template");
  template.innerHTML = await response.text();
  const content = template.content;
  document.getElementById("composer").prepend(content.getElementById("image-preview"));
  document.body.append(content.getElementById("image-drop-overlay"));
}

function loadControlsOnce() {
  controlsReady ??= loadControls();
  return controlsReady;
}

async function setDropOverlayVisible(isVisible) {
  if (isVisible !== isDropOverlayVisible) {
    isDropOverlayVisible = isVisible;
    await loadControlsOnce();
    const overlay = document.getElementById("image-drop-overlay");
    overlay.hidden = !isVisible;
    // Centers the message over the chat area rather than the whole window.
    overlay.style.paddingLeft = `${document.querySelector(".main").getBoundingClientRect().left}px`;
  }
}

function hasFiles(event) {
  return event.dataTransfer?.types.includes("Files");
}

export function setupImageDrop() {
  document.addEventListener("dragover", (event) => {
    if (hasFiles(event)) {
      // Without this the browser leaves the app and opens the dropped file.
      event.preventDefault();
      setDropOverlayVisible(true);
    }
  });
  document.addEventListener("dragleave", (event) => {
    if (hasFiles(event) && !event.relatedTarget) {
      setDropOverlayVisible(false);
    }
  });
  document.addEventListener("drop", (event) => {
    if (hasFiles(event)) {
      event.preventDefault();
      setDropOverlayVisible(false);
      attachUserFiles([...event.dataTransfer.files]);
    }
  });
}

function readAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(reader.result));
    reader.addEventListener("error", () => reject(new Error(`Couldn't read ${file.name}.`)));
    reader.readAsDataURL(file);
  });
}

export function readAttachedImages() {
  return Promise.all(attachedFiles.filter(isImage).map(readAsDataUrl));
}

export function clearAttachedImages() {
  attachedFiles = attachedFiles.filter((file) => !isImage(file));
  if (controlsReady) renderPreview();
}

export function readAttachedDocuments() {
  return attachedFiles.filter(isPdf);
}

export function hasAttachedDocuments() {
  return attachedFiles.some(isPdf);
}

export function clearAttachedDocuments() {
  attachedFiles = attachedFiles.filter((file) => !isPdf(file));
  if (controlsReady) renderPreview();
}
