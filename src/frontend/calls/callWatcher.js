import { requestJson } from "../shared/httpClient.js";
import * as chatStore from "../chat/chatStore.js";
import { addMessageBubble } from "../chat/messagesView.js";

const CHECK_INTERVAL_MS = 10000;
const statusLine = document.getElementById("call-status");

let activeCalls = new Map();
let nextCheck = null;

function showStatus() {
  const names = [...activeCalls.values()].map((call) => call.contactName);
  statusLine.textContent = names.length > 0 ? `Calling ${names.join(", ")}…` : "";
  statusLine.hidden = names.length === 0;
}

/** The backend already saved the result; this only shows it without a page reload. */
function showResult(call) {
  const chat = chatStore.getChats().find((candidate) => candidate.id === call.conversationId);
  if (!chat || !call.resultMessage) return;
  chatStore.addSavedMessage(chat, { role: "assistant", content: call.resultMessage, model: null });
  if (chat.id === chatStore.getActiveChatId()) {
    addMessageBubble("assistant", call.resultMessage);
  }
}

/** Checks now, and keeps checking only while a call is running. */
export async function watchCalls() {
  clearTimeout(nextCheck);
  nextCheck = null;

  let calls;
  try {
    ({ calls } = await requestJson("GET", "/api/calls"));
  } catch (error) {
    console.error("Could not check calls:", error);
    if (activeCalls.size > 0) {
      nextCheck = setTimeout(watchCalls, CHECK_INTERVAL_MS);
    }
    return;
  }

  for (const call of calls) {
    if (activeCalls.has(call.id) && call.status !== "calling") {
      showResult(call);
    }
  }
  activeCalls = new Map(calls.filter((call) => call.status === "calling").map((call) => [call.id, call]));
  showStatus();
  if (activeCalls.size > 0) {
    nextCheck = setTimeout(watchCalls, CHECK_INTERVAL_MS);
  }
}
