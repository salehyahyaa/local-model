import { requestJson } from "../shared/httpClient.js";

export const listPrograms = () => requestJson("GET", "/api/autostart");
export const removeProgram = (id) => requestJson("DELETE", `/api/autostart/${encodeURIComponent(id)}`);
