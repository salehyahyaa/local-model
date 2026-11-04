import { requestJson as request } from "../shared/httpClient.js";

export const loadState = () => request("GET", "/api/state");
export const createConversation = () => request("POST", "/api/conversations");
export const updateConversation = (id, changes) => request("PATCH", `/api/conversations/${id}`, changes);
export const deleteConversation = (id) => request("DELETE", `/api/conversations/${id}`);
export const addMessage = (id, role, content, model) =>
  request("POST", `/api/conversations/${id}/messages`, { role, content, model });
export const deleteLastMessage = (id) => request("DELETE", `/api/conversations/${id}/messages/last`);
export const updateSettings = (changes) => request("PATCH", "/api/settings", changes);

/** Uploads one PDF to a saved message. Returns { id, fileName, sizeBytes }. */
export async function uploadDocument(messageId, file) {
  const response = await fetch(`/api/messages/${messageId}/documents`, {
    method: "POST",
    headers: { "Content-Type": "application/pdf", "X-File-Name": encodeURIComponent(file.name) },
    body: file,
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(errorBody?.error ?? `Upload failed (HTTP ${response.status})`);
  }
  return response.json();
}
