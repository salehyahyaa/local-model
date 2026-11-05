import { requestJson } from "../shared/httpClient.js";

export const listIntegrations = () => requestJson("GET", "/api/integrations");
export const addMcpServer = (server) => requestJson("POST", "/api/integrations/mcp", server);
export const addApiIntegration = (integration) => requestJson("POST", "/api/integrations/api", integration);
export const connectGmail = (connection) => requestJson("POST", "/api/integrations/gmail", connection);
export const setIntegrationEnabled = (kind, id, enabled) =>
  requestJson("PATCH", `/api/integrations/${kind}/${id}`, { enabled });
export const removeIntegration = (kind, id) => requestJson("DELETE", `/api/integrations/${kind}/${id}`);
