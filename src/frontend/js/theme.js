const themeToggleButton = document.getElementById("theme-toggle-button");
const sunIcon = document.getElementById("sun-icon");
const moonIcon = document.getElementById("moon-icon");

function toggleTheme() {
  const root = document.documentElement;
  const isDark = root.dataset.theme === "dark";
  root.dataset.theme = isDark ? "light" : "dark";
  sunIcon.hidden = isDark;
  moonIcon.hidden = !isDark;
}

export function setupThemeToggle() {
  themeToggleButton.addEventListener("click", toggleTheme);
}
