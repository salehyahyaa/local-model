import * as chatStore from "../chat/chatStore.js";
import { pinIconSvg } from "./icons.js";

const chatList = document.getElementById("chat-list");
const pinnedList = document.getElementById("pinned-list");
const pinnedLabel = document.getElementById("pinned-label");
const recentsLabel = document.getElementById("recents-label");

let searchText = "";
let renamingChatId = null;
let isShowingArchive = false;
let onChatRightClick = () => {};

export function setSearchText(text) {
  searchText = text.trim().toLowerCase();
  renderChatList();
}

export function toggleArchiveView() {
  isShowingArchive = !isShowingArchive;
  renderChatList();
  return isShowingArchive;
}

export function startRenaming(chatId) {
  renamingChatId = chatId;
  renderChatList();
}

export function onRightClick(handler) {
  onChatRightClick = handler;
}

export function renderChatList() {
  chatList.innerHTML = "";
  pinnedList.innerHTML = "";
  let pinnedCount = 0;

  for (const chat of chatStore.getChats()) {
    if (searchText && !chat.title.toLowerCase().includes(searchText)) continue;
    if (chat.isArchived !== isShowingArchive) continue;
    const chatListItem = createChatListItem(chat);
    if (chat.isPinned && !isShowingArchive) {
      pinnedList.appendChild(chatListItem);
      pinnedCount += 1;
    } else {
      chatList.appendChild(chatListItem);
    }
  }

  pinnedLabel.hidden = pinnedCount === 0;
  recentsLabel.textContent = isShowingArchive ? "Archived" : "Recents";
}

function createChatListItem(chat) {
  const chatListItem = document.createElement("div");
  chatListItem.className = "chat-list-item";
  if (chat.id === chatStore.getActiveChatId()) {
    chatListItem.classList.add("active");
  }
  chatListItem.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    onChatRightClick(chat.id, event.clientX, event.clientY);
  });

  if (chat.id === renamingChatId) {
    chatListItem.appendChild(createRenameInput(chat));
  } else {
    chatListItem.append(createTitleButton(chat), createPinButton(chat));
  }
  return chatListItem;
}

function createTitleButton(chat) {
  const titleButton = document.createElement("button");
  titleButton.type = "button";
  titleButton.className = "chat-title-button";
  titleButton.textContent = chat.title;
  titleButton.addEventListener("click", () => {
    if (chatStore.isBusy()) return;
    chatStore.selectChat(chat.id);
  });
  return titleButton;
}

function createPinButton(chat) {
  const pinButton = document.createElement("button");
  pinButton.type = "button";
  pinButton.className = "pin-button";
  if (chat.isPinned) {
    pinButton.classList.add("pinned");
  }
  pinButton.title = chat.isPinned ? "Unpin" : "Pin";
  pinButton.innerHTML = pinIconSvg;
  pinButton.addEventListener("click", () => chatStore.togglePin(chat.id));
  return pinButton;
}

function createRenameInput(chat) {
  const renameInput = document.createElement("input");
  renameInput.type = "text";
  renameInput.className = "rename-input";
  renameInput.value = chat.title;

  let isFinished = false;
  function finishRenaming(shouldSave) {
    if (isFinished) return;
    isFinished = true;
    renamingChatId = null;
    const newTitle = shouldSave ? renameInput.value.trim() : "";
    chatStore.renameChat(chat.id, newTitle);
  }

  renameInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") finishRenaming(true);
    if (event.key === "Escape") finishRenaming(false);
  });
  renameInput.addEventListener("blur", () => finishRenaming(true));

  requestAnimationFrame(() => {
    renameInput.focus();
    renameInput.select();
  });
  return renameInput;
}
