function handleEvent(event, reply, callbacks) {
  if (event.type === "text") {
    reply.text += event.text;
    callbacks.onText(reply.text);
  } else if (event.type === "tool") {
    callbacks.onToolUse(event.label);
  } else if (event.type === "approval") {
    callbacks.onApproval(event);
  } else if (event.type === "error") {
    reply.text += `\n[Error: ${event.message}]`;
    callbacks.onText(reply.text);
  }
}

export async function streamChatReply(messages, conversationId, callbacks) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, conversationId, canApprove: true }),
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(errorBody?.error ?? `Request failed (HTTP ${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const reply = { text: "" };
  let bufferedText = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    bufferedText += decoder.decode(value, { stream: true });
    const lines = bufferedText.split("\n");
    bufferedText = lines.pop();
    for (const line of lines) {
      if (line.trim()) {
        handleEvent(JSON.parse(line), reply, callbacks);
      }
    }
  }
  if (bufferedText.trim()) {
    handleEvent(JSON.parse(bufferedText), reply, callbacks);
  }
  return reply.text;
}
