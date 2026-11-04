import * as chatStore from "./chatStore.js";
import { streamChatReply } from "./chatApi.js";
import { addMessageBubble, addToolNote, scrollToBottom } from "./messagesView.js";
import { getSelectedModelId, IMAGE_GENERATION_MODEL_ID } from "../models/modelPicker.js";

export async function sendMessage(text) {
  const chat = chatStore.getActiveChat();
  // Read once so switching models mid-reply can't change what this exchange is saved under.
  const model = getSelectedModelId();
  if (model === IMAGE_GENERATION_MODEL_ID) {
    const { sendImageMessage } = await import("../models/imageGeneration/view.js");
    return sendImageMessage(chat, text);
  }

  chatStore.setBusy(true);
  chatStore.addMessage(chat, "user", text, model);
  addMessageBubble("user", text);

  const replyBubble = addMessageBubble("assistant", "");
  replyBubble.classList.add("pending");

  try {
    const replyText = await streamChatReply(chat.messages, {
      onText: (partialReply) => {
        replyBubble.textContent = partialReply;
        scrollToBottom();
      },
      onToolUse: (label) => addToolNote(label, replyBubble),
    });
    chatStore.addMessage(chat, "assistant", replyText, model);
    return replyText;
  } catch (error) {
    replyBubble.textContent = error.message;
    chatStore.removeLastMessage(chat);
    return null;
  } finally {
    replyBubble.classList.remove("pending");
    chatStore.setBusy(false);
  }
}
