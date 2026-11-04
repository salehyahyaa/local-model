import { requestJson as request } from "../shared/httpClient.js";

export const loadState = () => request("GET", "/api/state");
export const createConversation = () => request("POST", "/api/conversations");
export const updateConversation = (id, changes) => request("PATCH", `/api/conversations/${id}`, changes);
export const deleteConversation = (id) => request("DELETE", `/api/conversations/${id}`);
export const addMessage = (id, role, content, model) =>
  request("POST", `/api/conversations/${id}/messages`, { role, content, model });
export const deleteLastMessage = (id) => request("DELETE", `/api/conversations/${id}/messages/last`);
export const updateSettings = (changes) => request("PATCH", "/api/settings", changes);
