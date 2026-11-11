/** keepalive lets a save finish even when the page is being closed, so no typed words are lost. */
async function send(method, url, body) {
  const response = await fetch(url, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    keepalive: method !== "GET",
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(errorBody?.error ?? `Request failed (HTTP ${response.status})`);
  }
  return response.json();
}

export const loadNotes = () => send("GET", "/api/notes");
export const createNote = (color, text = "") => send("POST", "/api/notes", { color, text });
export const updateNote = (noteId, changes) => send("PATCH", `/api/notes/${noteId}`, changes);
export const deleteNote = (noteId) => send("DELETE", `/api/notes/${noteId}`);
