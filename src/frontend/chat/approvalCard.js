import { requestJson } from "../shared/httpClient.js";
import { scrollToBottom } from "./messagesView.js";

function createDetailRow(name, value) {
  const row = document.createElement("div");
  row.className = "approval-detail";
  const label = document.createElement("span");
  label.className = "approval-detail-name";
  label.textContent = name;
  const content = document.createElement("span");
  content.className = "approval-detail-value";
  content.textContent = typeof value === "string" ? value : JSON.stringify(value);
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

/** Shows exactly what will run. The model's reply stays on hold until this is answered. */
export function addApprovalCard(approval, beforeElement) {
  const card = document.createElement("div");
  card.className = "approval-card";

  const title = document.createElement("div");
  title.className = "approval-title";
  title.textContent = `Approve ${approval.label}?`;
  card.appendChild(title);
  for (const [name, value] of Object.entries(approval.details)) {
    card.appendChild(createDetailRow(name, value));
  }

  const actions = document.createElement("div");
  actions.className = "approval-actions";

  async function answer(approved) {
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
  scrollToBottom();
}
