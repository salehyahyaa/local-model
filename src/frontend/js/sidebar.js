import * as chatStore from "./chatStore.js";
import * as chatListView from "./chatListView.js";

const sidebar = document.getElementById("sidebar");
const sidebarToggleButton = document.getElementById("sidebar-toggle-button");
const searchButton = document.getElementById("search-button");
const searchInput = document.getElementById("search-input");
const newChatButton = document.getElementById("new-chat-button");

function toggleSidebar() {
  sidebar.classList.toggle("collapsed");
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
    sidebar.classList.remove("collapsed");
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
