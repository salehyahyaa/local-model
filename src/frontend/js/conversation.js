import * as chatStore from "./chatStore.js";
import { streamChatReply } from "./chatApi.js";
import { addMessageBubble, scrollToBottom } from "./messagesView.js";

export async function sendMessage(text) {
  const chat = chatStore.getActiveChat();
  chatStore.setBusy(true);
  chatStore.addMessage(chat, "user", text);
  addMessageBubble("user", text);

  const replyBubble = addMessageBubble("assistant", "");
  replyBubble.classList.add("pending");

  try {
    const replyText = await streamChatReply(chat.messages, (partialReply) => {
      replyBubble.textContent = partialReply;
      scrollToBottom();
    });
    chatStore.addMessage(chat, "assistant", replyText);
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
