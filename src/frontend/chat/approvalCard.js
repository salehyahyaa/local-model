import { createLogo } from "../integrations/logos.js";
import { requestJson } from "../shared/httpClient.js";
import { scrollToBottom } from "./messagesView.js";

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
const DATE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;

// The event's title or an email's subject leads the card in bold, and its description or body follows as plain
// text. Neither needs a name beside it.
const HEADLINE_FIELDS = ["summary", "title", "subject"];
const BODY_FIELDS = ["description", "body"];

// Date first and weekday last: "Nov 11, 2026, 10:00 AM, Wednesday".
function readableDate(date, timeZone) {
  const day = date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric", timeZone });
  const weekday = date.toLocaleDateString(undefined, { weekday: "long", timeZone });
  return { day, weekday };
}

// Turns ISO dates and times from any tool into readable text. Anything else is shown as sent.
function readableValue(value) {
  if (typeof value !== "string") return JSON.stringify(value);
  const text = value.trim();
  if (DATE_ONLY.test(text)) {
    const { day, weekday } = readableDate(new Date(`${text}T00:00:00Z`), "UTC");
    return `${day}, ${weekday}`;
  }
  if (DATE_TIME.test(text)) {
    const date = new Date(text);
    const { day, weekday } = readableDate(date);
    const time = date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    return `${day}, ${time}, ${weekday}`;
  }
  return value;
}

// "create_event" → "Create event", so code names read like words.
function readableName(name) {
  const words = name.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
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

  // Every change the model asked for in one step is on this one card, and one answer covers them all.
  const actions = approval.actions;
  for (const action of actions) {
    const block = document.createElement("div");
    block.className = "approval-action";
    if (actions.length > 1) {
      const heading = document.createElement("div");
      heading.className = "approval-action-title";
      heading.textContent = readableName(action.label.split(" → ").pop());
      block.appendChild(heading);
    }
    const details = Object.entries(action.details);
    const headline = details.find(([name]) => HEADLINE_FIELDS.includes(name));
    if (headline) {
      const title = document.createElement("div");
      title.className = "approval-headline";
      title.textContent = readableValue(headline[1]);
      block.appendChild(title);
    }
    for (const [name, value] of details) {
      if (headline && name === headline[0]) continue;
      if (!BODY_FIELDS.includes(name)) block.appendChild(createDetailRow(name, value));
    }
    for (const [name, value] of details) {
      // A description that only repeats the title says nothing new.
      if (!BODY_FIELDS.includes(name) || (headline && String(value).trim() === String(headline[1]).trim())) continue;
      const body = document.createElement("div");
      body.className = "approval-body";
      body.textContent = readableValue(value);
      block.appendChild(body);
    }
    card.appendChild(block);
  }

  // The logo of each integration these changes go to, once each, at the top right.
  const logos = document.createElement("div");
  logos.className = "approval-logos";
  const seen = new Set();
  for (const { integration } of actions) {
    if (!integration?.name || seen.has(integration.name)) continue;
    seen.add(integration.name);
    logos.appendChild(createLogo(integration));
  }
  card.prepend(logos);

  const buttons = document.createElement("div");
  buttons.className = "approval-actions";

  async function answer(approved) {
    setWaitingCard(null);
    buttons.replaceChildren();
    buttons.textContent = approved ? "Approved" : "Denied";
    try {
      await requestJson("POST", `/api/chat/approvals/${encodeURIComponent(approval.id)}`, { approved });
    } catch (error) {
      buttons.textContent = error.message;
    }
  }

  buttons.append(
    createButton("Deny", "secondary-button", () => answer(false)),
    createButton("Approve", "save-button", () => answer(true)),
  );
  card.appendChild(buttons);

  beforeElement.parentNode.insertBefore(card, beforeElement);
  setWaitingCard({ approval, actions: buttons });
  scrollToBottom();
}
