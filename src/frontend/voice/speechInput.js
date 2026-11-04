const FINISH_MESSAGE = "finish";
const STREAM_FAILED_MESSAGE = "The transcription stream failed.";

function toPcm16(samples) {
  const pcm = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    pcm[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
  }
  return pcm.buffer;
}

/**
 * Streams one utterance to the backend, which passes it live to Deepgram.
 * onText(text) runs each time the words heard so far change.
 * `result` gives the final text. It rejects on failure, and gives "" after cancel().
 */
export function openSpeechStream({ onText }) {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/api/transcribe/stream`);
  const waitingToSend = [];
  let isSettled = false;
  let settle;
  let fail;

  const result = new Promise((resolve, reject) => {
    settle = (text) => {
      isSettled = true;
      resolve(text);
    };
    fail = (message) => {
      isSettled = true;
      reject(new Error(message));
    };
  });
  // A failure is reported when the utterance ends, so it mustn't count as unhandled until then.
  result.catch(() => {});

  function send(data) {
    if (socket.readyState === WebSocket.OPEN) {
      socket.send(data);
    } else if (socket.readyState === WebSocket.CONNECTING) {
      waitingToSend.push(data);
    }
  }

  socket.onopen = () => {
    for (const data of waitingToSend) {
      socket.send(data);
    }
    waitingToSend.length = 0;
  };

  socket.onmessage = (event) => {
    if (isSettled) return;
    const message = JSON.parse(event.data);
    if (message.error) {
      fail(message.error);
    } else if (message.done) {
      settle(message.text);
    } else {
      onText(message.text);
    }
  };

  socket.onclose = () => {
    if (!isSettled) fail(STREAM_FAILED_MESSAGE);
  };

  return {
    result,
    sendAudio: (samples) => send(toPcm16(samples)),
    finish: () => send(FINISH_MESSAGE),
    cancel: () => {
      if (!isSettled) settle("");
      socket.close();
    },
  };
}
