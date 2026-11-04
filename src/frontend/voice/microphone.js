export const SAMPLE_RATE = 16000;

let audioContext = null;
let mediaStream = null;

export async function startMicrophone(onAudioChunk) {
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });
  await audioContext.audioWorklet.addModule("/assets/voice/audioCaptureProcessor.js");

  const source = audioContext.createMediaStreamSource(mediaStream);
  const captureNode = new AudioWorkletNode(audioContext, "audio-capture-processor");
  captureNode.port.onmessage = (event) => onAudioChunk(event.data);
  source.connect(captureNode);
}

export function stopMicrophone() {
  if (mediaStream) {
    for (const track of mediaStream.getTracks()) {
      track.stop();
    }
    mediaStream = null;
  }
  if (audioContext) {
    audioContext.close();
    audioContext = null;
  }
}
