import * as chatStore from "../../chat/chatStore.js";
import { addImageToBubble, addMessageBubble } from "../../chat/messagesView.js";
import { createImages } from "./api.js";
import { clearAttachedImages, readAttachedImages } from "../../chat/attachment.js";

export async function sendImageMessage(chat, prompt) {
  chatStore.setBusy(true);
  const userBubble = addMessageBubble("user", prompt);
  const replyBubble = addMessageBubble("assistant", "");
  replyBubble.classList.add("pending");
  try {
    const images = await readAttachedImages();
    clearAttachedImages();
    for (const image of images) {
      addImageToBubble(userBubble, image);
    }
    const noun = images.length > 1 ? `${images.length} images` : "your image";
    replyBubble.textContent = `Making ${noun}. This can take a long time. `;

    const { userMessage, assistantMessage } = await createImages(chat.id, prompt, images);
    chatStore.addSavedMessage(chat, userMessage);
    chatStore.addSavedMessage(chat, assistantMessage);
    replyBubble.textContent = "";
    for (const imageFile of assistantMessage.imageFiles) {
      addImageToBubble(replyBubble, `/api/images/${imageFile}`);
    }
  } catch (error) {
    replyBubble.textContent = error.message;
  } finally {
    replyBubble.classList.remove("pending");
    chatStore.setBusy(false);
  }
  return null;
}
