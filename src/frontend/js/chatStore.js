const DEFAULT_TITLE = "New chat";

const listeners = { chatsChanged: [], activeChatChanged: [] };

let chats = [];
let activeChatId = null;
let nextChatId = 1;
let isWaitingForReply = false;

function notify(eventName) {
  for (const listener of listeners[eventName]) {
    listener();
  }
}

export function subscribe(eventName, listener) {
  listeners[eventName].push(listener);
}

export function getChats() {
  return chats;
}

export function getActiveChat() {
  return chats.find((chat) => chat.id === activeChatId);
}

export function getActiveChatId() {
  return activeChatId;
}

export function isBusy() {
  return isWaitingForReply;
}

export function setBusy(busy) {
  isWaitingForReply = busy;
}

export function createChat() {
  const chat = { id: nextChatId, title: DEFAULT_TITLE, messages: [], isPinned: false };
  nextChatId += 1;
  chats.unshift(chat);
  activeChatId = chat.id;
  notify("chatsChanged");
  notify("activeChatChanged");
}

export function selectChat(chatId) {
  activeChatId = chatId;
  notify("chatsChanged");
  notify("activeChatChanged");
}

export function deleteChat(chatId) {
  if (isWaitingForReply && chatId === activeChatId) return;
  chats = chats.filter((chat) => chat.id !== chatId);
  if (chats.length === 0) {
    createChat();
    return;
  }
  if (chatId === activeChatId) {
    selectChat(chats[0].id);
    return;
  }
  notify("chatsChanged");
}

export function renameChat(chatId, newTitle) {
  const chat = chats.find((chat) => chat.id === chatId);
  if (chat && newTitle) {
    chat.title = newTitle;
  }
  notify("chatsChanged");
}

export function togglePin(chatId) {
  const chat = chats.find((chat) => chat.id === chatId);
  chat.isPinned = !chat.isPinned;
  notify("chatsChanged");
}

export function addMessage(chat, role, content) {
  chat.messages.push({ role, content });
  if (role === "user" && chat.title === DEFAULT_TITLE) {
    chat.title = content.slice(0, 40);
    notify("chatsChanged");
  }
}

export function removeLastMessage(chat) {
  chat.messages.pop();
}
