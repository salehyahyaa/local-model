import { robinhoodLogoSvg } from "../integrations/logos.js";

const PAGE_ADDRESS = "#agentic-purchases";
const REFRESH_MS = 15000;
/** Other full-page views close themselves when this fires. */
const VIEW_OPENED_EVENT = "main-view-opened";
const STATUS_LABELS = { POSTED: "Paid", PENDING: "Pending", DECLINED: "Declined", REFUNDED: "Refunded" };
const DECLINE_LABELS = {
  AGENT_PENDING: "Waiting for your approval",
  AGENT_REJECTED: "You rejected it",
  TRANSACTION_ERROR: "Transaction error",
};

const view = document.getElementById("agentic-purchases-view");
const chatView = document.querySelector(".main");
const openButton = document.getElementById("agentic-purchases-button");
const connectionBox = document.getElementById("purchases-connection");
const status = document.getElementById("purchases-status");
const list = document.getElementById("purchases-list");
const empty = document.getElementById("purchases-empty");

let refreshTimer = null;

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function showStatus(text) {
  status.textContent = text ?? "";
  status.hidden = !text;
}

function money(value) {
  return `$${Number(value).toFixed(2)}`;
}

function formatDate(iso) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function logo() {
  return Object.assign(createElement("span", "integration-logo purchases-logo"), { innerHTML: robinhoodLogoSvg });
}

function renderConnection(connection) {
  if (!connection) {
    connectionBox.replaceChildren(
      createElement("span", "purchases-connection-text", "Not connected. Add Robinhood Banking from + → Add integration."),
    );
    return;
  }
  const text = createElement("div", "purchases-connection-text");
  text.append(createElement("div", "purchases-connection-name", connection.name));
  const card = connection.card;
  let detail = "Connected";
  if (connection.problem) detail = connection.problem;
  else if (card) detail = `Agentic card ${card.active ? "active" : card.cardStatus.toLowerCase()} · ${money(card.spentThisMonth)} spent this month`;
  text.append(createElement("div", `purchases-connection-detail${connection.problem ? " problem" : ""}`, detail));
  connectionBox.replaceChildren(logo(), text);
}

function statusText(purchase) {
  const label = STATUS_LABELS[purchase.status] ?? purchase.status.toLowerCase();
  const reason = purchase.declineReason ? DECLINE_LABELS[purchase.declineReason] ?? purchase.declineReason.toLowerCase().replaceAll("_", " ") : "";
  return reason ? `${label}: ${reason}` : label;
}

function renderPurchase(purchase) {
  const row = createElement("li", "purchase");
  const body = createElement("div", "purchase-body");
  body.append(createElement("div", "purchase-merchant", purchase.merchant));
  body.append(createElement("div", "purchase-meta", `${formatDate(purchase.purchasedAt)} · Purchase #${purchase.id}`));
  const side = createElement("div", "purchase-side");
  side.append(createElement("div", `purchase-amount${purchase.status === "DECLINED" ? " declined" : ""}`, money(purchase.total)));
  side.append(createElement("span", `purchase-status ${purchase.status.toLowerCase()}`, statusText(purchase)));
  row.append(body, side);
  return row;
}

async function refresh() {
  clearTimeout(refreshTimer);
  try {
    const response = await fetch("/api/agentic-purchases");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const { connection, purchases } = await response.json();
    renderConnection(connection);
    list.replaceChildren(...purchases.map(renderPurchase));
    empty.hidden = purchases.length > 0;
    showStatus("");
  } catch {
    showStatus("Couldn't load purchases. Is the database running?");
  }
  if (!view.hidden) refreshTimer = setTimeout(refresh, REFRESH_MS);
}

function openPurchases() {
  document.dispatchEvent(new CustomEvent(VIEW_OPENED_EVENT, { detail: "agentic-purchases" }));
  chatView.hidden = true;
  view.hidden = false;
  openButton.classList.add("active");
  openButton.setAttribute("aria-pressed", "true");
  history.replaceState(null, "", PAGE_ADDRESS);
  refresh();
}

function closePurchases() {
  clearTimeout(refreshTimer);
  view.hidden = true;
  chatView.hidden = false;
  openButton.classList.remove("active");
  openButton.setAttribute("aria-pressed", "false");
  if (location.hash === PAGE_ADDRESS) history.replaceState(null, "", location.pathname);
}

export function setupAgenticPurchases() {
  openButton.setAttribute("aria-pressed", "false");
  openButton.addEventListener("click", () => (view.hidden ? openPurchases() : closePurchases()));
  document.getElementById("sidebar").addEventListener("click", (event) => {
    if (!view.hidden && event.target.closest(".chat-title-button, #new-chat-button")) closePurchases();
  });
  document.addEventListener(VIEW_OPENED_EVENT, (event) => {
    if (event.detail !== "agentic-purchases" && !view.hidden) closePurchases();
  });
  if (location.hash === PAGE_ADDRESS) openPurchases();
}
