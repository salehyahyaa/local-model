import * as autostartApi from "./autostartApi.js";

const moreButton = document.getElementById("more-button");
const menu = document.getElementById("more-menu");
const autostartButton = document.getElementById("autostart-button");
const section = document.getElementById("autostart-section");
const list = document.getElementById("autostart-list");
const message = document.getElementById("autostart-message");

const removeIconSvg =
  '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>';

function showMessage(text) {
  message.textContent = text;
  message.hidden = !text;
}

function confirmationText(program) {
  if (program.isThisApp) {
    return `Remove ${program.name} from auto-start? It stops now, so this page stops working until you start the app again. Other programs aren't removed.`;
  }
  return `Remove ${program.name} from auto-start? It stops now and won't start at login.`;
}

async function removeProgram(program, item) {
  if (!window.confirm(confirmationText(program))) return;
  try {
    await autostartApi.removeProgram(program.id);
  } catch (error) {
    showMessage(error.message);
    return;
  }
  if (program.isThisApp) {
    // The app answers this menu's requests, so the other programs stay listed but can't be changed until it's back.
    item.remove();
    for (const button of list.querySelectorAll(".autostart-remove-button")) {
      button.disabled = true;
      button.title = "Start the app again to change this";
    }
    showMessage(`${program.name} has stopped and won't start at login. Other programs are still set to auto-start.`);
    return;
  }
  await refreshList();
}

function createProgramItem(program) {
  const item = document.createElement("div");
  item.className = "autostart-item";

  const details = document.createElement("div");
  details.className = "autostart-details";
  const name = document.createElement("div");
  name.textContent = program.name;
  const status = document.createElement("div");
  status.className = "autostart-status";
  status.textContent = program.isRunning ? "Running · starts at login" : "Not running · starts at login";
  details.append(name, status);

  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.className = "autostart-remove-button";
  removeButton.title = `Remove ${program.name} from auto-start`;
  removeButton.setAttribute("aria-label", removeButton.title);
  removeButton.innerHTML = removeIconSvg;
  removeButton.addEventListener("click", () => removeProgram(program, item));

  item.append(details, removeButton);
  return item;
}

async function refreshList() {
  showMessage("");
  let programs;
  try {
    ({ programs } = await autostartApi.listPrograms());
  } catch (error) {
    list.innerHTML = "";
    showMessage(error.message);
    return;
  }
  list.replaceChildren(...programs.map(createProgramItem));
  if (programs.length === 0) {
    showMessage("Nothing starts automatically.");
  }
}

function setSectionOpen(isOpen) {
  section.hidden = !isOpen;
  autostartButton.setAttribute("aria-expanded", String(isOpen));
}

function openMenu() {
  const buttonPosition = moreButton.getBoundingClientRect();
  menu.style.top = `${buttonPosition.bottom + 6}px`;
  menu.style.right = `${window.innerWidth - buttonPosition.right}px`;
  menu.hidden = false;
  moreButton.setAttribute("aria-expanded", "true");
}

function closeMenu() {
  menu.hidden = true;
  moreButton.setAttribute("aria-expanded", "false");
  setSectionOpen(false);
}

export function setupAutostartMenu() {
  moreButton.addEventListener("click", (event) => {
    event.stopPropagation();
    if (menu.hidden) {
      openMenu();
    } else {
      closeMenu();
    }
  });

  autostartButton.addEventListener("click", () => {
    const isOpening = section.hidden;
    setSectionOpen(isOpening);
    if (isOpening) refreshList();
  });

  // Inside the menu, a click can replace the clicked element, so it must never count as clicking outside.
  menu.addEventListener("click", (event) => event.stopPropagation());
  document.addEventListener("click", () => {
    if (!menu.hidden) closeMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !menu.hidden) closeMenu();
  });
}
