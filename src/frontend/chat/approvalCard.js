import { requestJson } from "../shared/httpClient.js";
import { scrollToBottom } from "./messagesView.js";

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
const DATE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;

// Turns ISO dates and times from any tool into "Thu, Nov 12, 6:30 PM". Anything else is shown as sent.
function readableValue(value) {
  if (typeof value !== "string") return JSON.stringify(value);
  const text = value.trim();
  if (DATE_ONLY.test(text)) {
    return new Date(`${text}T00:00:00Z`).toLocaleDateString(undefined, {
      weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
    });
  }
  if (DATE_TIME.test(text)) {
    return new Date(text).toLocaleString(undefined, {
      weekday: "short", month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
    });
  }
  return value;
}

// "create_event" → "Create event", so code names read like words.
function readableName(name) {
  const words = name.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function readableTitle(label) {
  return label.replace(/\b[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+\b/g, readableName);
}

function createDetailRow(name, value) {
  const row = document.createElement("div");
  row.className = "approval-detail";
  const label = document.createElement("span");
  label.className = "approval-detail-name";
  label.textContent = readableName(name);
  const content = document.createElement("span");
  content.className = "approval-detail-value";
  content.textContent = readableValue(value);
  row.append(label, content);
  return row;
}

function createButton(text, className, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = text;
  button.addEventListener("click", onClick);
  return button;
}

// The card still waiting for an answer. Only one can wait at a time, because the reply is on hold until it's answered.
let waitingCard = null;

function setWaitingCard(card) {
  waitingCard = card;
  document.dispatchEvent(new CustomEvent("approval-wait-changed"));
}

export function hasWaitingApproval() {
  return waitingCard !== null;
}

export function forgetWaitingApproval() {
  setWaitingCard(null);
}

/** Cancels the waiting card and hands the owner's message to the model. Throws if the card can't take it. */
export async function replaceWaitingApproval(followUp) {
  const { approval, actions } = waitingCard;
  setWaitingCard(null);
  actions.replaceChildren();
  actions.textContent = "Not done. Changed by your message";
  try {
    await requestJson("POST", `/api/chat/approvals/${encodeURIComponent(approval.id)}`, { followUp });
  } catch (error) {
    actions.textContent = error.message;
    throw error;
  }
}

/** Shows exactly what will run. The model's reply stays on hold until this is answered or the owner sends a message. */
export function addApprovalCard(approval, beforeElement) {
  const card = document.createElement("div");
  card.className = "approval-card";

  const title = document.createElement("div");
  title.className = "approval-title";
  title.textContent = `Approve ${readableTitle(approval.label)}?`;
  card.appendChild(title);
  for (const [name, value] of Object.entries(approval.details)) {
    card.appendChild(createDetailRow(name, value));
  }

  const actions = document.createElement("div");
  actions.className = "approval-actions";

  async function answer(approved) {
    setWaitingCard(null);
    actions.replaceChildren();
    actions.textContent = approved ? "Approved" : "Denied";
    try {
      await requestJson("POST", `/api/chat/approvals/${encodeURIComponent(approval.id)}`, { approved });
    } catch (error) {
      actions.textContent = error.message;
    }
  }

  actions.append(
    createButton("Deny", "secondary-button", () => answer(false)),
    createButton("Approve", "save-button", () => answer(true)),
  );
  card.appendChild(actions);

  beforeElement.parentNode.insertBefore(card, beforeElement);
  setWaitingCard({ approval, actions });
  scrollToBottom();
}
