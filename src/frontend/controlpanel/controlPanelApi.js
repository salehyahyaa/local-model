import { requestJson } from "../shared/httpClient.js";

export const loadTasks = () => requestJson("GET", "/api/tasks");
export const completeTask = (taskId) => requestJson("POST", `/api/tasks/${taskId}/complete`);
export const reopenTask = (taskId) => requestJson("POST", `/api/tasks/${taskId}/reopen`);
