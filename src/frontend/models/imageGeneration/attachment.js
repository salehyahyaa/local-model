import { addMessageBubble } from "../../chat/messagesView.js";

const BASE_URL = "/assets/models/imageGeneration";
const SUPPORTED_TYPES = ["image/png", "image/jpeg", "image/webp"];
const MAX_IMAGES = 20;
const MAX_FILE_BYTES = 20 * 1024 * 1024;
const MAX_TOTAL_BYTES = 100 * 1024 * 1024;

const removeIconSvg =
  '<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>';

let attachedFiles = [];
let controlsReady = null;

function totalBytes(files) {
  return files.reduce((total, file) => total + file.size, 0);
}

function createThumbnail(file) {
  const frame = document.createElement("div");
  frame.className = "image-preview-frame";

  const image = document.createElement("img");
  image.src = URL.createObjectURL(file);
  image.alt = file.name;
  image.addEventListener("load", () => URL.revokeObjectURL(image.src), { once: true });

  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.className = "image-preview-remove";
  removeButton.title = "Remove image";
  removeButton.innerHTML = removeIconSvg;
  removeButton.addEventListener("click", () => {
    attachedFiles = attachedFiles.filter((attached) => attached !== file);
    renderPreview();
  });

  frame.append(image, removeButton);
  return frame;
}

function renderPreview() {
  const preview = document.getElementById("image-preview");
  preview.replaceChildren(...attachedFiles.map(createThumbnail));
  preview.hidden = attachedFiles.length === 0;
}

/** Returns the images among these files, telling the user in the chat if there are none. */
export function usableImages(files) {
  const images = files.filter((file) => SUPPORTED_TYPES.includes(file.type) && file.size <= MAX_FILE_BYTES);
  if (images.length === 0) {
    addMessageBubble("assistant", "Only PNG, JPEG or WebP images up to 20 MB can be used right now.");
  }
  return images;
}

export async function attachFiles(files) {
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
    addMessageBubble("assistant", `You can send up to ${MAX_IMAGES} images in a message, so some weren't added.`);
  }
  if (skippedForSize) {
    addMessageBubble("assistant", "A message's images can total up to 100 MB, so some weren't added.");
  }
}

async function loadControls() {
  const stylesheet = document.createElement("link");
  stylesheet.rel = "stylesheet";
  stylesheet.href = `${BASE_URL}/imageGeneration.css`;
  document.head.appendChild(stylesheet);

  const response = await fetch(`${BASE_URL}/imageGeneration.html`);
  const template = document.createElement("template");
  template.innerHTML = await response.text();
  const content = template.content;
  document.getElementById("add-button").after(content.getElementById("image-attachment"));
  document.getElementById("composer").prepend(content.getElementById("image-preview"));
  document.body.append(content.getElementById("image-drop-overlay"));

  const fileInput = document.getElementById("image-file-input");
  document.getElementById("attach-image-button").addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    const images = usableImages([...fileInput.files]);
    if (images.length > 0) {
      attachFiles(images);
    }
    fileInput.value = "";
  });
}

function loadControlsOnce() {
  controlsReady ??= loadControls();
  return controlsReady;
}

export async function setAttachmentVisible(isVisible) {
  await loadControlsOnce();
  document.getElementById("image-attachment").hidden = !isVisible;
  if (!isVisible) {
    clearAttachedImages();
  }
}

export async function setDropOverlayVisible(isVisible) {
  await loadControlsOnce();
  const overlay = document.getElementById("image-drop-overlay");
  overlay.hidden = !isVisible;
  // Centers the message over the chat area rather than the whole window.
  overlay.style.paddingLeft = `${document.querySelector(".main").getBoundingClientRect().left}px`;
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
  return Promise.all(attachedFiles.map(readAsDataUrl));
}

export function clearAttachedImages() {
  attachedFiles = [];
  renderPreview();
}
