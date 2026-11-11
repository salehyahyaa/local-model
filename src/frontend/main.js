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
import { watchCalls } from "./calls/callWatcher.js";
import { applySelectedModel, setupModelPicker } from "./models/modelPicker.js";
import { setupImageDrop } from "./chat/attachment.js";
import { setupAutostartMenu } from "./autostart/autostartMenu.js";
import { setupSettingsPanel } from "./settings/settingsPanel.js";
import { setupNotes } from "./notes/notes.js";
import { setupScheduled } from "./scheduled_jobs/scheduled_jobs.js";

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
setupModelPicker();
setupImageDrop();
setupAutostartMenu();
setupSettingsPanel();
setupNotes();
setupScheduled();
setupControlPanelLoader();

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

function loadStylesheet(href) {
  return new Promise((resolve, reject) => {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    link.onload = resolve;
    link.onerror = () => reject(new Error(`Couldn't load ${href}`));
    document.head.append(link);
  });
}

/** The Control Panel's code and styles load the first time it's opened, keeping them out of startup. */
function setupControlPanelLoader() {
  const button = document.getElementById("control-panel-button");
  const start = async () => {
    const [{ setupControlPanel, openControlPanel }] = await Promise.all([
      import("./controlpanel/controlPanel.js"),
      loadStylesheet("/assets/controlpanel/controlpanel.css"),
    ]);
    setupControlPanel();
    return openControlPanel;
  };
  if (location.hash === "#control-panel") {
    start();
  } else {
    button.addEventListener("click", async () => (await start())(), { once: true });
  }
}
