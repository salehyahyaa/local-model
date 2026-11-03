const messagesEl = document.getElementById("messages");
const emptyEl = document.getElementById("empty");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const statusEl = document.getElementById("status");
const clearBtn = document.getElementById("clear");

let history = [];
let busy = false;

async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    statusEl.textContent = `model: ${data.model}`;
    statusEl.className = "status ok";
  } catch {
    statusEl.textContent = "backend unreachable";
    statusEl.className = "status bad";
  }
}

function addMessage(role, text) {
  emptyEl.hidden = true;
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.textContent = text;
  messagesEl.appendChild(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return el;
}

function autosize() {
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
}

async function send(text) {
  busy = true;
  sendBtn.disabled = true;
  history.push({ role: "user", content: text });
  addMessage("user", text);
  const botEl = addMessage("assistant", "");
  botEl.classList.add("pending");

  let reply = "";
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      reply += decoder.decode(value, { stream: true });
      botEl.textContent = reply;
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
    history.push({ role: "assistant", content: reply });
  } catch (err) {
    botEl.textContent = `Error: ${err.message}`;
    history.pop();
  } finally {
    botEl.classList.remove("pending");
    busy = false;
    sendBtn.disabled = false;
    input.focus();
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || busy) return;
  input.value = "";
  autosize();
  send(text);
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});
input.addEventListener("input", autosize);

clearBtn.addEventListener("click", () => {
  if (busy) return;
  history = [];
  messagesEl.querySelectorAll(".msg").forEach((m) => m.remove());
  emptyEl.hidden = false;
});

checkHealth();
