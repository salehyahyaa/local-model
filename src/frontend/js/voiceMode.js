import * as chatStore from "./chatStore.js";
import { setVoiceActive } from "./composer.js";
import { startMicrophone, stopMicrophone } from "./microphone.js";
import { createSpeechDetector } from "./speechDetector.js";
import { stopSpeaking } from "./speechOutput.js";
import { addMessageBubble } from "./messagesView.js";

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
  onUtterance: () => {},
});

function setVoiceState(newState) {
  voiceState = newState;
  voiceOrb.classList.toggle("thinking", newState === "thinking");
  voiceOrb.classList.toggle("speaking", newState === "speaking");
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
