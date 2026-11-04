import * as stateApi from "./stateApi.js";

const DEFAULT_TITLE = "New chat";

const listeners = { chatsChanged: [], activeChatChanged: [], saveFailed: [] };

let chats = [];
let activeChatId = null;
let isWaitingForReply = false;
let isOffline = false;
let nextOfflineId = -1;
let saveQueue = Promise.resolve();

function notify(eventName, detail) {
  for (const listener of listeners[eventName]) {
    listener(detail);
  }
}

// Saves run one at a time, in order, so e.g. "add message" then "remove last message" can't swap.
function save(saveFunction) {
  if (isOffline) return Promise.resolve(null);
  const result = saveQueue.then(saveFunction);
  saveQueue = result.catch((error) => {
    console.error("Could not save change:", error);
    notify("saveFailed", error);
  });
  return result;
}

function findChat(chatId) {
  return chats.find((chat) => chat.id === chatId);
}

export function subscribe(eventName, listener) {
  listeners[eventName].push(listener);
}

export function getChats() {
  return chats;
}

export function getActiveChat() {
  return findChat(activeChatId);
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

export function saveSettings(changes) {
  save(() => stateApi.updateSettings(changes));
}

/** Loads saved chats. Returns { settings } on success, or { error } if nothing could be loaded. */
export async function load() {
  let state;
  try {
    state = await stateApi.loadState();
  } catch (error) {
    console.error("Could not load saved chats:", error);
    isOffline = true;
    await createChat();
    return { error };
  }

  chats = state.conversations;
  const savedActiveChat = findChat(state.settings.activeConversationId);
  if (savedActiveChat && !savedActiveChat.isArchived) {
    activeChatId = savedActiveChat.id;
    notify("chatsChanged");
    notify("activeChatChanged");
  } else {
    const firstChat = chats.find((chat) => !chat.isArchived);
    if (firstChat) {
      selectChat(firstChat.id);
    } else {
      await createChat();
    }
  }
  return { settings: state.settings };
}

function createOfflineChat() {
  const chat = { id: nextOfflineId, title: DEFAULT_TITLE, messages: [], isPinned: false, isArchived: false };
  nextOfflineId -= 1;
  return chat;
}

export async function createChat() {
  let chat;
  try {
    chat = (await save(() => stateApi.createConversation())) ?? createOfflineChat();
  } catch {
    chat = createOfflineChat();
  }
  chats.unshift(chat);
  selectChat(chat.id);
}

export function selectChat(chatId) {
  activeChatId = chatId;
  save(() => stateApi.updateSettings({ activeConversationId: chatId }));
  notify("chatsChanged");
  notify("activeChatChanged");
}

export function deleteChat(chatId) {
  if (isWaitingForReply && chatId === activeChatId) return;
  chats = chats.filter((chat) => chat.id !== chatId);
  save(() => stateApi.deleteConversation(chatId));
  const nextChat = chats.find((chat) => !chat.isArchived);
  if (chatId !== activeChatId) {
    notify("chatsChanged");
  } else if (nextChat) {
    selectChat(nextChat.id);
  } else {
    createChat();
  }
}

export function renameChat(chatId, newTitle) {
  const chat = findChat(chatId);
  if (chat && newTitle && newTitle !== chat.title) {
    chat.title = newTitle;
    save(() => stateApi.updateConversation(chatId, { title: newTitle }));
  }
  notify("chatsChanged");
}

export function archiveChat(chatId) {
  if (isWaitingForReply && chatId === activeChatId) return;
  const chat = findChat(chatId);
  chat.isArchived = true;
  chat.isPinned = false;
  save(() => stateApi.updateConversation(chatId, { isArchived: true, isPinned: false }));
  if (chatId === activeChatId) {
    const nextChat = chats.find((chat) => !chat.isArchived);
    if (nextChat) {
      selectChat(nextChat.id);
    } else {
      createChat();
    }
    return;
  }
  notify("chatsChanged");
}

export function togglePin(chatId) {
  const chat = findChat(chatId);
  chat.isPinned = !chat.isPinned;
  save(() => stateApi.updateConversation(chatId, { isPinned: chat.isPinned }));
  notify("chatsChanged");
}

function titleChatFromFirstMessage(chat, role, content) {
  if (role === "user" && chat.title === DEFAULT_TITLE) {
    const title = content.slice(0, 40);
    chat.title = title;
    save(() => stateApi.updateConversation(chat.id, { title }));
    notify("chatsChanged");
  }
}

export function addMessage(chat, role, content, model) {
  chat.messages.push({ role, content, model });
  save(() => stateApi.addMessage(chat.id, role, content, model));
  titleChatFromFirstMessage(chat, role, content);
}

/** For messages the backend already saved, such as an image request and its result. */
export function addSavedMessage(chat, message) {
  chat.messages.push(message);
  titleChatFromFirstMessage(chat, message.role, message.content);
}

export function removeLastMessage(chat) {
  chat.messages.pop();
  save(() => stateApi.deleteLastMessage(chat.id));
}
