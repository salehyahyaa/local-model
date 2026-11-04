import { SAMPLE_RATE } from "./microphone.js";

const MINIMUM_THRESHOLD = 0.012;
const NOISE_MULTIPLIER = 3;
const SILENCE_TO_END_MS = 900;
const MINIMUM_SPEECH_MS = 350;
const PRE_ROLL_MS = 300;
const CALIBRATION_MS = 500;
const MAX_UTTERANCE_MS = 20 * 60 * 1000;

function calculateRms(samples) {
  let sumOfSquares = 0;
  for (const sample of samples) {
    sumOfSquares += sample * sample;
  }
  return Math.sqrt(sumOfSquares / samples.length);
}

function durationMs(sampleCount) {
  return (sampleCount / SAMPLE_RATE) * 1000;
}

// The quietest quarter of the window, so words spoken during calibration don't count as room noise.
function estimateNoiseFloor(chunks) {
  const levels = chunks.map(calculateRms).sort((a, b) => a - b);
  return levels[Math.floor(levels.length / 4)];
}

function joinChunks(chunks) {
  const totalLength = chunks.reduce((total, chunk) => total + chunk.length, 0);
  const joined = new Float32Array(totalLength);
  let offset = 0;
  for (const chunk of chunks) {
    joined.set(chunk, offset);
    offset += chunk.length;
  }
  return joined;
}

export function createSpeechDetector({ onLevel, onUtterance }) {
  let noiseFloor = MINIMUM_THRESHOLD / NOISE_MULTIPLIER;
  let isSpeaking = false;
  let preRollChunks = [];
  let utteranceChunks = [];
  let speechSampleCount = 0;
  let silenceSampleCount = 0;
  let utteranceSampleCount = 0;
  let calibrationChunks = [];
  let calibrationSampleCount = 0;
  let isCalibrating = true;

  function reset() {
    isSpeaking = false;
    preRollChunks = [];
    utteranceChunks = [];
    speechSampleCount = 0;
    silenceSampleCount = 0;
    utteranceSampleCount = 0;
    calibrationChunks = [];
    calibrationSampleCount = 0;
    isCalibrating = true;
    onLevel(0);
  }

  function calibrate(chunk) {
    calibrationChunks.push(chunk);
    calibrationSampleCount += chunk.length;
    if (durationMs(calibrationSampleCount) < CALIBRATION_MS) return;

    noiseFloor = estimateNoiseFloor(calibrationChunks);
    isCalibrating = false;
    // Replay the window so anything said during calibration is still captured.
    const bufferedChunks = calibrationChunks;
    calibrationChunks = [];
    for (const bufferedChunk of bufferedChunks) {
      process(bufferedChunk);
    }
  }

  function keepPreRoll(chunk) {
    preRollChunks.push(chunk);
    let preRollSamples = preRollChunks.reduce((total, item) => total + item.length, 0);
    while (durationMs(preRollSamples) > PRE_ROLL_MS) {
      preRollSamples -= preRollChunks.shift().length;
    }
  }

  function finishUtterance() {
    const hadEnoughSpeech = durationMs(speechSampleCount) >= MINIMUM_SPEECH_MS;
    const samples = joinChunks(utteranceChunks);
    reset();
    if (hadEnoughSpeech) {
      onUtterance(samples);
    }
  }

  function process(chunk) {
    if (isCalibrating) {
      calibrate(chunk);
      return;
    }

    const rms = calculateRms(chunk);
    const threshold = Math.max(MINIMUM_THRESHOLD, noiseFloor * NOISE_MULTIPLIER);
    const isLoud = rms > threshold;
    onLevel(Math.min(1, rms / (threshold * 4)));

    if (!isSpeaking) {
      if (isLoud) {
        isSpeaking = true;
        utteranceChunks = [...preRollChunks, chunk];
        utteranceSampleCount = utteranceChunks.reduce((total, item) => total + item.length, 0);
        speechSampleCount = chunk.length;
        silenceSampleCount = 0;
      } else {
        noiseFloor = noiseFloor * 0.95 + rms * 0.05;
        keepPreRoll(chunk);
      }
      return;
    }

    utteranceChunks.push(chunk);
    utteranceSampleCount += chunk.length;
    if (isLoud) {
      speechSampleCount += chunk.length;
      silenceSampleCount = 0;
    } else {
      silenceSampleCount += chunk.length;
    }

    if (durationMs(silenceSampleCount) >= SILENCE_TO_END_MS || durationMs(utteranceSampleCount) >= MAX_UTTERANCE_MS) {
      finishUtterance();
    }
  }

  return { process, reset };
}
