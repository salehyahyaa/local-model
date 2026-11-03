import * as chatStore from "./chatStore.js";
import { renderChatList } from "./chatListView.js";
import { renderMessages } from "./messagesView.js";
import { setupComposer, focusInput } from "./composer.js";
import { setupContextMenu } from "./contextMenu.js";
import { setupSidebar } from "./sidebar.js";
import { setupThemeToggle } from "./theme.js";
import { setupVoiceMode } from "./voiceMode.js";

chatStore.subscribe("chatsChanged", renderChatList);
chatStore.subscribe("activeChatChanged", () => {
  renderMessages();
  focusInput();
});

setupSidebar();
setupContextMenu();
setupComposer();
setupThemeToggle();
setupVoiceMode();

chatStore.createChat();
