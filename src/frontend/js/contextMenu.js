import * as chatStore from "./chatStore.js";
import * as chatListView from "./chatListView.js";

const chatContextMenu = document.getElementById("chat-context-menu");
const renameChatButton = document.getElementById("rename-chat-button");
const deleteChatButton = document.getElementById("delete-chat-button");

let contextMenuChatId = null;

function openContextMenu(chatId, positionX, positionY) {
  contextMenuChatId = chatId;
  chatContextMenu.hidden = false;
  chatContextMenu.style.left = `${positionX}px`;
  chatContextMenu.style.top = `${positionY}px`;
}

function closeContextMenu() {
  chatContextMenu.hidden = true;
  contextMenuChatId = null;
}

export function setupContextMenu() {
  chatListView.onRightClick(openContextMenu);

  renameChatButton.addEventListener("click", () => {
    const chatIdToRename = contextMenuChatId;
    closeContextMenu();
    chatListView.startRenaming(chatIdToRename);
  });

  deleteChatButton.addEventListener("click", () => {
    const chatIdToDelete = contextMenuChatId;
    closeContextMenu();
    chatStore.deleteChat(chatIdToDelete);
  });

  document.addEventListener("click", (event) => {
    if (!chatContextMenu.contains(event.target)) {
      closeContextMenu();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeContextMenu();
    }
  });
}
