import * as chatStore from "./chat/chatStore.js";
import { renderChatList } from "./sidebar/chatListView.js";
import { addMessageBubble, renderMessages } from "./chat/messagesView.js";
import { setupComposer, focusInput } from "./chat/composer.js";
import { setupContextMenu } from "./sidebar/contextMenu.js";
import { applySidebarCollapsed, setupSidebar } from "./sidebar/sidebar.js";
import { applyTheme, setupThemeToggle } from "./theme/theme.js";
import { setupVoiceMode } from "./voice/voiceMode.js";
import { setupIntegrationsMenu } from "./integrations/integrationsMenu.js";
import { setupIntegrationForm } from "./integrations/integrationForm.js";
import { setupGmailForm } from "./integrations/gmailForm.js";
import { setupGoogleCalendarForm } from "./integrations/googleCalendarForm.js";
import { setupPhoneCallsForm } from "./integrations/phoneCallsForm.js";
import { watchCalls } from "./calls/callWatcher.js";
import { applySelectedModel, setupModelPicker } from "./models/modelPicker.js";
import { setupImageDrop } from "./chat/attachment.js";
import { setupAutostartMenu } from "./autostart/autostartMenu.js";
import { setupSettingsPanel } from "./settings/settingsPanel.js";
import { setupControlPanel } from "./controlpanel/controlPanel.js";

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
setupIntegrationsMenu();
setupIntegrationForm();
setupGmailForm();
setupGoogleCalendarForm();
setupPhoneCallsForm();
setupModelPicker();
setupImageDrop();
setupAutostartMenu();
setupSettingsPanel();
setupControlPanel();

let hasShownSaveError = false;
chatStore.subscribe("saveFailed", (error) => {
  if (hasShownSaveError) return;
  hasShownSaveError = true;
  addMessageBubble("assistant", `Couldn't save your changes: ${error.message}`);
});

const { settings, error } = await chatStore.load();
if (settings) {
  applyTheme(settings.theme);
  applySidebarCollapsed(settings.sidebarCollapsed);
  applySelectedModel(settings.selectedModel);
  watchCalls();
} else {
  addMessageBubble("assistant", `Couldn't load saved chats (${error.message}). Changes won't be saved.`);
}
