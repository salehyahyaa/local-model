import { saveSettings } from "../chat/chatStore.js";

const themeToggleButton = document.getElementById("theme-toggle-button");
const sunIcon = document.getElementById("sun-icon");
const moonIcon = document.getElementById("moon-icon");

export function applyTheme(theme) {
  const isDark = theme === "dark";
  document.documentElement.dataset.theme = theme;
  sunIcon.hidden = !isDark;
  moonIcon.hidden = isDark;
}

function toggleTheme() {
  const newTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(newTheme);
  saveSettings({ theme: newTheme });
}

export function setupThemeToggle() {
  themeToggleButton.addEventListener("click", toggleTheme);
}
