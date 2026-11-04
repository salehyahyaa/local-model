import { requestJson } from "../../shared/httpClient.js";

export const createImages = (conversationId, prompt, images) =>
  requestJson("POST", `/api/conversations/${conversationId}/images`, { prompt, images });
