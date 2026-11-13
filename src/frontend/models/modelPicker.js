import { saveSettings } from "../chat/chatStore.js";

export const IMAGE_GENERATION_MODEL_ID = "image-generation";

const MODEL_OPTIONS = [
  { id: "model", name: "Model", description: "Ask, learn, and explore", placeholder: "Ask anything..." },
  {
    id: IMAGE_GENERATION_MODEL_ID,
    name: "Image Generation",
    description: "Edit any existing image",
    placeholder: "Describe an image...",
    redDot: true,
  },
];

const button = document.getElementById("model-button");
const nameLabel = document.getElementById("model-name");
const menu = document.getElementById("model-menu");
const messageInput = document.getElementById("message-input");

const checkIconSvg =
  '<svg class="model-check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="5 12 10 17 19 7"/></svg>';

let selectedOptionId = MODEL_OPTIONS[0].id;

export function getSelectedModelId() {
  return selectedOptionId;
}

function createRedDot() {
  const dot = document.createElement("span");
  dot.className = "red-dot";
  dot.setAttribute("aria-hidden", "true");
  return dot;
}

function createMenuItem(option, selectedOption) {
  const isSelected = option === selectedOption;
  const item = document.createElement("button");
  item.type = "button";
  item.className = "context-menu-item model-menu-item";
  item.setAttribute("role", "menuitemradio");
  item.setAttribute("aria-checked", String(isSelected));

  const details = document.createElement("span");
  details.className = "model-menu-item-details";
  const name = document.createElement("span");
  name.textContent = option.name;
  if (option.redDot) name.append(" ", createRedDot());
  const description = document.createElement("span");
  description.className = "model-menu-item-description";
  description.textContent = option.description;
  details.append(name, description);
  item.appendChild(details);
  if (isSelected) {
    item.insertAdjacentHTML("beforeend", checkIconSvg);
  }

  item.addEventListener("click", () => {
    selectOption(option);
    closeMenu();
    messageInput.focus();
  });
  return item;
}

function showOption(option) {
  selectedOptionId = option.id;
  nameLabel.textContent = option.name;
  if (option.redDot) nameLabel.append(" ", createRedDot());
  messageInput.placeholder = option.placeholder;
  menu.replaceChildren(...MODEL_OPTIONS.map((menuOption) => createMenuItem(menuOption, option)));
}

function selectOption(option) {
  saveSettings({ selectedModel: option.id });
  showOption(option);
}

function openMenu() {
  const buttonPosition = button.getBoundingClientRect();
  menu.style.left = `${buttonPosition.left}px`;
  menu.style.top = `${buttonPosition.bottom + 6}px`;
  menu.hidden = false;
  button.setAttribute("aria-expanded", "true");
}

function closeMenu() {
  menu.hidden = true;
  button.setAttribute("aria-expanded", "false");
}

export function applySelectedModel(savedOptionId) {
  showOption(MODEL_OPTIONS.find((option) => option.id === savedOptionId) ?? MODEL_OPTIONS[0]);
}

export function setupModelPicker() {
  applySelectedModel();

  button.addEventListener("click", () => {
    if (menu.hidden) {
      openMenu();
    } else {
      closeMenu();
    }
  });

  // Capture phase so this still runs when another button stops the click from bubbling.
  document.addEventListener(
    "click",
    (event) => {
      if (!button.contains(event.target) && !menu.contains(event.target)) {
        closeMenu();
      }
    },
    true,
  );

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeMenu();
    }
  });
}
