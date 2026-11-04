function cleanForSpeech(text) {
  return text.replace(/[*#`_>~]/g, "").replace(/\[(.*?)\]\(.*?\)/g, "$1");
}

function splitIntoSentences(text) {
  return text.match(/[^.!?\n]+[.!?]*/g)?.map((sentence) => sentence.trim()).filter(Boolean) ?? [];
}

function speakSentence(sentence) {
  return new Promise((resolve) => {
    const utterance = new SpeechSynthesisUtterance(sentence);
    utterance.onend = resolve;
    utterance.onerror = resolve;
    speechSynthesis.speak(utterance);
  });
}

let isStopped = false;

export async function speak(text) {
  isStopped = false;
  for (const sentence of splitIntoSentences(cleanForSpeech(text))) {
    if (isStopped) return;
    await speakSentence(sentence);
  }
}

export function stopSpeaking() {
  isStopped = true;
  speechSynthesis.cancel();
}
