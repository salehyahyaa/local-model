import * as chatStore from "../chat/chatStore.js";
import { setVoiceActive } from "../chat/composer.js";
import { startMicrophone, stopMicrophone } from "./microphone.js";
import { createSpeechDetector } from "./speechDetector.js";
import { speak, stopSpeaking } from "./speechOutput.js";
import { transcribe } from "./speechInput.js";
import { sendMessage } from "../chat/conversation.js";
import { addMessageBubble } from "../chat/messagesView.js";

const voiceButton = document.getElementById("voice-button");
const muteButton = document.getElementById("mute-button");
const endVoiceButton = document.getElementById("end-voice-button");
const voiceOrb = document.getElementById("voice-orb");
const voiceOrbSphere = voiceOrb.querySelector(".voice-orb-sphere");

let isActive = false;
let isMuted = false;
let voiceState = "idle";

const speechDetector = createSpeechDetector({
  onLevel: (level) => voiceOrbSphere.style.setProperty("--level", level.toFixed(3)),
  onUtterance: handleUtterance,
});

function setVoiceState(newState) {
  voiceState = newState;
  voiceOrb.classList.toggle("thinking", newState === "thinking");
  voiceOrb.classList.toggle("speaking", newState === "speaking");
}

async function handleUtterance(samples) {
  if (!isActive || chatStore.isBusy()) return;
  setVoiceState("thinking");
  try {
    const text = await transcribe(samples);
    if (text && isActive) {
      const replyText = await sendMessage(text);
      if (replyText && isActive) {
        setVoiceState("speaking");
        await speak(replyText);
      }
    }
  } catch (error) {
    addMessageBubble("assistant", error.message);
  }
  if (isActive) {
    speechDetector.reset();
    setVoiceState("listening");
  }
}

function handleAudioChunk(chunk) {
  if (!isActive || isMuted || voiceState !== "listening") return;
  speechDetector.process(chunk);
}

async function startVoiceMode() {
  if (isActive || chatStore.isBusy()) return;
  try {
    await startMicrophone(handleAudioChunk);
  } catch (error) {
    addMessageBubble("assistant", `Could not access the microphone: ${error.message}`);
    return;
  }
  isActive = true;
  voiceOrb.hidden = false;
  setVoiceActive(true);
  speechDetector.reset();
  setVoiceState("listening");
}

function endVoiceMode() {
  isActive = false;
  stopMicrophone();
  stopSpeaking();
  speechDetector.reset();
  setMuted(false);
  setVoiceState("idle");
  voiceOrb.hidden = true;
  setVoiceActive(false);
}

function setMuted(muted) {
  isMuted = muted;
  muteButton.classList.toggle("muted", muted);
  voiceOrb.classList.toggle("muted", muted);
  muteButton.title = muted ? "Unmute" : "Mute";
  if (muted) {
    speechDetector.reset();
  }
}

export function setupVoiceMode() {
  voiceButton.addEventListener("click", startVoiceMode);
  endVoiceButton.addEventListener("click", endVoiceMode);
  muteButton.addEventListener("click", () => setMuted(!isMuted));
}
