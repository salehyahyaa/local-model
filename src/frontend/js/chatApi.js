export async function streamChatReply(messages, onTextChunk) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(errorBody?.error ?? `Request failed (HTTP ${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let replyText = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    replyText += decoder.decode(value, { stream: true });
    onTextChunk(replyText);
  }
  return replyText;
}
