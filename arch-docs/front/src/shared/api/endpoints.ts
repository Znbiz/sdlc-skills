import { httpClient, sseUrl } from "./http-client";
import type {
  CliAuthStatusResponse,
  CliEngine,
  ConversationItemsResponse,
  ConversationRepositoryResponse,
  ConversationResponse,
  DocsFileResponse,
  DocsTreeNode,
  GitConnectionDetailResponse,
  GitConnectionSummaryResponse,
  GitConnectionType,
  GitSshPublicKeyResponse,
  InitAuthResponse,
  LlmProviderConnectionDetailResponse,
  LlmProviderConnectionSummaryResponse,
  LlmProviderConnectionTestResponse,
  ResponseStatusResponse,
} from "./models";

export const cliAuthApi = {
  getStatus: () => httpClient.get<CliAuthStatusResponse>("/rest/cli-auth/"),
  initAuth: (cliEngine: CliEngine) => httpClient.post<InitAuthResponse>("/rpc/cli-auth/init/", { cli_engine: cliEngine }),
  getAuthSession: (authSessionId: string) => httpClient.get<InitAuthResponse>(`/rest/cli-auth/auth-sessions/${authSessionId}/`),
  submitAuthCode: (authSessionId: string, code: string) =>
    httpClient.post<InitAuthResponse>(`/rpc/cli-auth/auth-sessions/${authSessionId}/submit-code/`, { code }),
  authSessionStreamUrl: (authSessionId: string) => sseUrl(`/rest/cli-auth/auth-sessions/${authSessionId}/stream/`),
};

export const gitConnectionsApi = {
  list: () => httpClient.get<GitConnectionSummaryResponse[]>("/rest/git-connections/"),
  get: (connectionId: string) =>
    httpClient.get<GitConnectionDetailResponse>(`/rest/git-connections/${encodeURIComponent(connectionId)}/`),
  create: (params: { host: string; connectionType: GitConnectionType; token?: string; username?: string }) =>
    httpClient.post<GitConnectionSummaryResponse>("/rest/git-connections/", {
      host: params.host,
      connection_type: params.connectionType,
      token: params.token,
      username: params.username,
    }),
  update: (
    connectionId: string,
    params: { host: string; connectionType: GitConnectionType; token?: string; username?: string },
  ) =>
    httpClient.put<GitConnectionSummaryResponse>(`/rest/git-connections/${encodeURIComponent(connectionId)}/`, {
      host: params.host,
      connection_type: params.connectionType,
      token: params.token,
      username: params.username,
    }),
  delete: (connectionId: string) => httpClient.delete<void>(`/rest/git-connections/${encodeURIComponent(connectionId)}/`),
};

export const gitSshApi = {
  getPublicKey: () => httpClient.get<GitSshPublicKeyResponse>("/rest/git-ssh/public-key/"),
};

export interface LlmProviderConnectionParams {
  name: string;
  baseUrl: string;
  model: string;
  token?: string;
  wireApi?: string;
  requiresOpenaiAuth?: boolean;
}

export const llmProvidersApi = {
  list: () => httpClient.get<LlmProviderConnectionSummaryResponse[]>("/rest/llm-providers/"),
  get: (connectionId: string) =>
    httpClient.get<LlmProviderConnectionDetailResponse>(`/rest/llm-providers/${encodeURIComponent(connectionId)}/`),
  create: (params: LlmProviderConnectionParams) =>
    httpClient.post<LlmProviderConnectionSummaryResponse>("/rest/llm-providers/", {
      name: params.name,
      base_url: params.baseUrl,
      model: params.model,
      token: params.token,
      wire_api: params.wireApi ?? "responses",
      requires_openai_auth: params.requiresOpenaiAuth ?? false,
    }),
  update: (connectionId: string, params: LlmProviderConnectionParams) =>
    httpClient.put<LlmProviderConnectionSummaryResponse>(`/rest/llm-providers/${encodeURIComponent(connectionId)}/`, {
      name: params.name,
      base_url: params.baseUrl,
      model: params.model,
      token: params.token,
      wire_api: params.wireApi ?? "responses",
      requires_openai_auth: params.requiresOpenaiAuth ?? false,
    }),
  delete: (connectionId: string) => httpClient.delete<void>(`/rest/llm-providers/${encodeURIComponent(connectionId)}/`),
  test: (connectionId: string) =>
    httpClient.post<LlmProviderConnectionTestResponse>(`/rest/llm-providers/${encodeURIComponent(connectionId)}/test/`),
};

export const workflowApi = {
  createConversation: () => httpClient.post<ConversationResponse>("/rest/conversations/"),
  listConversations: (limit?: number) => httpClient.get<ConversationResponse[]>("/rest/conversations/", { query: { limit } }),
  getConversation: (conversationId: string) => httpClient.get<ConversationResponse>(`/rest/conversations/${conversationId}/`),
  listItems: (conversationId: string) => httpClient.get<ConversationItemsResponse>(`/rest/conversations/${conversationId}/items/`),
  conversationStreamUrl: (conversationId: string) => sseUrl(`/rest/conversations/${conversationId}/stream/`),
  createResponse: <TInput extends object = Record<string, unknown>>(params: {
    conversationId: string;
    workflowType: string;
    input?: TInput;
  }) =>
    httpClient.post<ResponseStatusResponse>("/rest/responses/", {
      conversation_id: params.conversationId,
      workflow_type: params.workflowType,
      input: params.input ?? {},
    }),
  getResponse: (responseId: string) => httpClient.get<ResponseStatusResponse>(`/rest/responses/${responseId}/`),
  listResponseItems: (responseId: string) => httpClient.get<ConversationItemsResponse>(`/rest/responses/${responseId}/items/`),
  submitAction: (
    responseId: string,
    params: { actionType: string; questionId?: string | null; answer?: string | null; field?: string | null; value?: unknown },
  ) =>
    httpClient.post<ResponseStatusResponse>(`/rest/responses/${responseId}/actions/`, {
      action_type: params.actionType,
      question_id: params.questionId ?? null,
      answer: params.answer ?? null,
      field: params.field ?? null,
      value: params.value ?? null,
    }),
};

export const conversationsApi = {
  deleteConversation: (conversationId: string) => httpClient.delete<void>(`/rest/conversations/${conversationId}/`),
  getRepositories: (conversationId: string) =>
    httpClient.get<ConversationRepositoryResponse[]>(`/rest/conversations/${conversationId}/repositories/`),
  setRepositories: (conversationId: string, entries: string[]) =>
    httpClient.put<ConversationRepositoryResponse[]>(`/rest/conversations/${conversationId}/repositories/`, { entries }),
  addRepository: (conversationId: string, entry: string) =>
    httpClient.post<ConversationRepositoryResponse[]>(`/rest/conversations/${conversationId}/repositories/`, { entry }),
  removeRepository: (conversationId: string, repositoryName: string) =>
    httpClient.delete<ConversationRepositoryResponse[]>(
      `/rest/conversations/${conversationId}/repositories/${encodeURIComponent(repositoryName)}/`,
    ),
  updateProductName: (conversationId: string, productName: string) =>
    httpClient.patch<ConversationResponse>(`/rest/conversations/${conversationId}/`, { product_name: productName }),
  listResponses: (conversationId: string) =>
    httpClient.get<ResponseStatusResponse[]>(`/rest/conversations/${conversationId}/responses/`),
};

export const workspaceApi = {
  getTree: (conversationId: string) => httpClient.get<DocsTreeNode>(`/rest/conversations/${conversationId}/workspace/tree/`),
  getFile: (conversationId: string, path: string) =>
    httpClient.get<DocsFileResponse>(`/rest/conversations/${conversationId}/workspace/file/`, { query: { path } }),
  deletePath: (conversationId: string, path: string) =>
    httpClient.delete<void>(`/rest/conversations/${conversationId}/workspace/file/`, { query: { path } }),
};
