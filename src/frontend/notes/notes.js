import * as api from "./notesApi.js";

const PAGE_ADDRESS = "#notes";
const SAVE_DELAY_MS = 600;
const COLORS = ["yellow", "pink", "blue", "green", "purple"];
/** Other full-page views (like the Control Panel) close themselves when this fires. */
const VIEW_OPENED_EVENT = "main-view-opened";

const view = document.getElementById("notes-view");
const chatView = document.querySelector(".main");
const openButton = document.getElementById("notes-button");
const tape = document.getElementById("notes-tape");
const drawer = document.getElementById("notes-drawer");

/** The Notes page and the drawer from the tape show the same notes in two places. */
const page = {
  board: document.getElementById("notes-board"),
  status: document.getElementById("notes-status"),
  newButton: document.getElementById("notes-plus-button"),
};
const bulletButton = document.getElementById("notes-bullet-button");
const dashButton = document.getElementById("notes-dash-button");
const copiedNotice = document.getElementById("notes-copied");
const BULLET = "•";
const DASH = "–";
const COPIED_NOTICE_MS = 1500;
const searchInput = document.getElementById("notes-search-input");
const plusSlot = document.querySelector(".notes-plus-slot");
const side = {
  board: document.getElementById("notes-drawer-board"),
  status: document.getElementById("notes-drawer-status"),
  newButton: document.getElementById("drawer-new-note-button"),
};

const pendingSaves = new Map();

function showStatus(surface, text) {
  surface.status.textContent = text ?? "";
  surface.status.hidden = !text;
}

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

/** Grows a note to fit its words; past the max height set in CSS it scrolls instead. */
function fitHeight(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${textarea.scrollHeight}px`;
}

function fitAll(surface) {
  surface.board.querySelectorAll(".note-text").forEach(fitHeight);
}

function saveSoon(surface, noteId, changes) {
  const pending = pendingSaves.get(noteId);
  clearTimeout(pending?.timer);
  const merged = { ...pending?.changes, ...changes };
  const timer = setTimeout(() => flushSave(noteId), SAVE_DELAY_MS);
  pendingSaves.set(noteId, { timer, changes: merged, surface });
}

async function flushSave(noteId) {
  const pending = pendingSaves.get(noteId);
  if (!pending) return;
  clearTimeout(pending.timer);
  pendingSaves.delete(noteId);
  try {
    await api.updateNote(noteId, pending.changes);
  } catch (error) {
    showStatus(pending.surface, `Couldn't save a note: ${error.message}`);
  }
}

function flushAllSaves() {
  return Promise.all([...pendingSaves.keys()].map(flushSave));
}

function renderNote(surface, note) {
  const card = createElement("article", `note note-${note.color}`);

  const text = createElement("textarea", "note-text");
  text.value = note.text;
  text.placeholder = "Write something…";
  text.setAttribute("aria-label", "Note");
  text.addEventListener("input", () => {
    fitHeight(text);
    saveSoon(surface, note.id, { text: text.value });
  });
  text.addEventListener("blur", () => flushSave(note.id));

  const footer = createElement("div", "note-footer");
  const remove = createElement("button", "note-delete");
  remove.type = "button";
  remove.title = "Delete note";
  remove.setAttribute("aria-label", "Delete note");
  remove.innerHTML =
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M6 7l1 13h10l1-13"/><path d="M9 7V4h6v3"/></svg>';
  remove.addEventListener("click", () => removeNote(surface, note.id, card));

  footer.append(remove);
  card.append(text, footer);
  return card;
}

function showEmptyIfNeeded(surface) {
  if (surface.board.querySelector(".note")) return;
  surface.board.replaceChildren(createElement("p", "notes-empty", "No notes yet."));
}

async function removeNote(surface, noteId, card) {
  clearTimeout(pendingSaves.get(noteId)?.timer);
  pendingSaves.delete(noteId);
  try {
    await api.deleteNote(noteId);
    card.remove();
    showEmptyIfNeeded(surface);
    if (surface === page) alignPlus();
    showStatus(surface, "");
  } catch (error) {
    showStatus(surface, `Couldn't delete the note: ${error.message}`);
  }
}

/** Returns true once the note is saved. Focuses it when it starts empty, so you can type straight away. */
async function addNote(surface, text = "") {
  surface.newButton.disabled = true;
  try {
    const note = await api.createNote(COLORS[0], text);
    surface.board.querySelector(".notes-empty")?.remove();
    const card = renderNote(surface, note);
    surface.board.prepend(card);
    surface.board.scrollTop = 0;
    const textarea = card.querySelector(".note-text");
    fitHeight(textarea);
    if (!text) textarea.focus();
    if (surface === page) alignPlus();
    showStatus(surface, "");
    return true;
  } catch (error) {
    showStatus(surface, `Couldn't add a note: ${error.message}`);
    return false;
  } finally {
    surface.newButton.disabled = false;
  }
}

/** Keeps the + level with the middle of the first note, however tall that note grows. */
let firstNote = null;
const firstNoteSize = new ResizeObserver(() => {
  plusSlot.style.height = firstNote?.isConnected ? `${firstNote.offsetHeight}px` : "";
});

function alignPlus() {
  const first = page.board.querySelector(".note:not([hidden])");
  if (first === firstNote) return;
  if (firstNote) firstNoteSize.unobserve(firstNote);
  firstNote = first;
  if (first) firstNoteSize.observe(first);
  else plusSlot.style.height = "";
}

/** Shows only notes containing the search words, matched like the chat search. */
function filterNotes() {
  const searchText = searchInput.value.trim().toLowerCase();
  page.board.querySelector(".notes-no-match")?.remove();
  const cards = [...page.board.querySelectorAll(".note")];
  for (const card of cards) {
    const text = card.querySelector(".note-text").value.toLowerCase();
    card.hidden = Boolean(searchText) && !text.includes(searchText);
  }
  if (searchText && cards.length && cards.every((card) => card.hidden)) {
    page.board.append(createElement("p", "notes-empty notes-no-match", "No notes match your search."));
  }
  alignPlus();
}

/** Waits for unsaved typing first, so reopening always shows the latest words. */
async function refreshNotes(surface) {
  await flushAllSaves();
  try {
    const { notes } = await api.loadNotes();
    surface.board.replaceChildren(...notes.map((note) => renderNote(surface, note)));
    showEmptyIfNeeded(surface);
    fitAll(surface);
    if (surface === page) filterNotes();
    showStatus(surface, "");
  } catch (error) {
    showStatus(surface, `Couldn't load notes: ${error.message}`);
  }
}

function openNotes() {
  closeDrawer();
  document.dispatchEvent(new CustomEvent(VIEW_OPENED_EVENT, { detail: "notes" }));
  chatView.hidden = true;
  view.hidden = false;
  openButton.classList.add("active");
  openButton.setAttribute("aria-pressed", "true");
  history.replaceState(null, "", PAGE_ADDRESS);
  refreshNotes(page);
}

function closeNotes() {
  flushAllSaves();
  view.hidden = true;
  chatView.hidden = false;
  openButton.classList.remove("active");
  openButton.setAttribute("aria-pressed", "false");
  if (location.hash === PAGE_ADDRESS) history.replaceState(null, "", location.pathname);
}

function openDrawer() {
  drawer.hidden = false;
  tape.classList.add("active");
  tape.setAttribute("aria-expanded", "true");
  refreshNotes(side);
}

function closeDrawer() {
  if (drawer.hidden) return;
  flushAllSaves();
  drawer.hidden = true;
  tape.classList.remove("active");
  tape.setAttribute("aria-expanded", "false");
}

let copiedTimer = null;

async function copyMark(mark, name) {
  try {
    await navigator.clipboard.writeText(mark);
    copiedNotice.textContent = `${name} copied`;
  } catch {
    copiedNotice.textContent = "Couldn't copy";
  }
  clearTimeout(copiedTimer);
  copiedTimer = setTimeout(() => (copiedNotice.textContent = ""), COPIED_NOTICE_MS);
}

export function setupNotes() {
  openButton.setAttribute("aria-pressed", "false");
  openButton.addEventListener("click", () => (view.hidden ? openNotes() : closeNotes()));
  page.newButton.addEventListener("click", () => addNote(page));
  searchInput.addEventListener("input", filterNotes);
  bulletButton.addEventListener("click", () => copyMark(BULLET, "Bullet"));
  dashButton.addEventListener("click", () => copyMark(DASH, "Dash"));

  tape.addEventListener("click", () => (drawer.hidden ? openDrawer() : closeDrawer()));
  side.newButton.addEventListener("click", () => addNote(side));
  document.getElementById("notes-drawer-close").addEventListener("click", closeDrawer);
  drawer.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeDrawer();
      tape.focus();
    }
  });

  document.getElementById("sidebar").addEventListener("click", (event) => {
    if (!view.hidden && event.target.closest(".chat-title-button, #new-chat-button")) closeNotes();
  });
  document.addEventListener(VIEW_OPENED_EVENT, (event) => {
    if (event.detail === "notes") return;
    closeDrawer();
    if (!view.hidden) closeNotes();
  });
  window.addEventListener("pagehide", flushAllSaves);
  if (location.hash === PAGE_ADDRESS) openNotes();
}
