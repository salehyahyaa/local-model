import * as chatStore from "./chatStore.js";
import { streamChatReply } from "./chatApi.js";
import { addApprovalCard, forgetWaitingApproval, replaceWaitingApproval } from "./approvalCard.js";
import {
  addDocumentCard,
  addMessageBubble,
  addToolNote,
  scrollToBottom,
  setBubbleText,
  setDocumentCardFailed,
  setDocumentCardSaved,
} from "./messagesView.js";
import { clearAttachedDocuments, readAttachedDocuments } from "./attachment.js";
import { getSelectedModelId, IMAGE_GENERATION_MODEL_ID } from "../models/modelPicker.js";
import { watchCalls } from "../calls/callWatcher.js";

let currentExchange = null;

/** Sends a message into the reply that's on hold for an approval, so it answers the card instead of starting over. */
export async function sendFollowUp(text) {
  const { chat, model, replyBubble } = currentExchange;
  await replaceWaitingApproval(text);
  replyBubble.before(addMessageBubble("user", text));
  chatStore.addMessage(chat, "user", text, model);
}

export async function sendMessage(text) {
  const chat = chatStore.getActiveChat();
  // Read once so switching models mid-reply can't change what this exchange is saved under.
  const model = getSelectedModelId();
  if (model === IMAGE_GENERATION_MODEL_ID) {
    const { sendImageMessage } = await import("../models/imageGeneration/view.js");
    return sendImageMessage(chat, text);
  }

  chatStore.setBusy(true);
  const documentFiles = readAttachedDocuments();
  clearAttachedDocuments();
  const userBubble = addMessageBubble("user", text);
  if (documentFiles.length > 0) {
    await saveWithDocuments(chat, text, model, documentFiles, userBubble);
  } else {
    chatStore.addMessage(chat, "user", text, model);
  }

  const replyBubble = addMessageBubble("assistant", "");
  replyBubble.classList.add("pending");
  currentExchange = { chat, model, replyBubble };

  try {
    const replyText = await streamChatReply(chat.messages, chat.id, {
      onText: (partialReply) => {
        setBubbleText(replyBubble, partialReply);
        scrollToBottom();
      },
      onToolUse: (label) => addToolNote(label, replyBubble),
      onApproval: (approval) => addApprovalCard(approval, replyBubble),
    });
    chatStore.addMessage(chat, "assistant", replyText, model);
    watchCalls();
    return replyText;
  } catch (error) {
    // Your message (and any PDFs) stay saved; only the reply failed.
    setBubbleText(replyBubble, error.message);
    return null;
  } finally {
    replyBubble.classList.remove("pending");
    currentExchange = null;
    chatStore.setBusy(false);
    forgetWaitingApproval();
  }
}

async function saveWithDocuments(chat, text, model, files, bubble) {
  const cards = files.map((file) => addDocumentCard(bubble, file.name));
  try {
    await chatStore.addMessageWithDocuments(chat, text, model, files, (index, document) =>
      setDocumentCardSaved(cards[index], document),
    );
  } catch (error) {
    for (const card of cards.filter((card) => card.classList.contains("uploading"))) {
      setDocumentCardFailed(card);
    }
    addMessageBubble("assistant", `Couldn't save the PDF: ${error.message}`);
  }
}
