import * as chatStore from "../chat/chatStore.js";
import * as chatListView from "./chatListView.js";

const sidebar = document.getElementById("sidebar");
const sidebarToggleButton = document.getElementById("sidebar-toggle-button");
const searchButton = document.getElementById("search-button");
const searchInput = document.getElementById("search-input");
const newChatButton = document.getElementById("new-chat-button");
const archiveButton = document.getElementById("archive-button");

export function applySidebarCollapsed(isCollapsed) {
  sidebar.classList.toggle("collapsed", isCollapsed);
}

function setSidebarCollapsed(isCollapsed) {
  applySidebarCollapsed(isCollapsed);
  chatStore.saveSettings({ sidebarCollapsed: isCollapsed });
}

function toggleSidebar() {
  setSidebarCollapsed(!sidebar.classList.contains("collapsed"));
}

function showSearch() {
  searchInput.hidden = false;
  searchInput.focus();
}

function hideSearch() {
  searchInput.hidden = true;
  searchInput.value = "";
  chatListView.setSearchText("");
}

function toggleSearch() {
  if (sidebar.classList.contains("collapsed")) {
    setSidebarCollapsed(false);
    showSearch();
  } else if (searchInput.hidden) {
    showSearch();
  } else {
    hideSearch();
  }
}

export function setupSidebar() {
  sidebarToggleButton.addEventListener("click", toggleSidebar);
  searchButton.addEventListener("click", toggleSearch);
  searchInput.addEventListener("input", () => chatListView.setSearchText(searchInput.value));

  archiveButton.addEventListener("click", () => {
    if (sidebar.classList.contains("collapsed")) setSidebarCollapsed(false);
    const isShowingArchive = chatListView.toggleArchiveView();
    archiveButton.classList.toggle("active", isShowingArchive);
  });

  newChatButton.addEventListener("click", () => {
    if (chatStore.isBusy()) return;
    chatStore.createChat();
  });

  document.addEventListener("keydown", (event) => {
    if (event.shiftKey && event.metaKey && event.key.toLowerCase() === "s") {
      event.preventDefault();
      toggleSidebar();
    }
  });
}
