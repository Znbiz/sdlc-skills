import { httpClient, sseUrl } from "./http-client";
import type {
  CheckGitAccessResponse,
  CliAuthStatusResponse,
  CliEngine,
  ConversationItemsResponse,
  ConversationResponse,
  DocsFileResponse,
  DocsTreeNode,
  GitCredentialsStatusResponse,
  InitAuthResponse,
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

export const gitCredentialsApi = {
  getStatus: () => httpClient.get<GitCredentialsStatusResponse>("/rest/git-credentials/"),
  setToken: (params: { host: string; token: string; username?: string }) =>
    httpClient.put<GitCredentialsStatusResponse>("/rest/git-credentials/personal-access-token/", params),
  deleteToken: (host: string) =>
    httpClient.delete<GitCredentialsStatusResponse>("/rest/git-credentials/personal-access-token/", { query: { host } }),
  checkAccess: (repositoryUrl: string) =>
    httpClient.post<CheckGitAccessResponse>("/rest/git-credentials/check-access/", { repository_url: repositoryUrl }),
};

export const workflowApi = {
  createConversation: () => httpClient.post<ConversationResponse>("/rest/conversations/"),
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

export const docsApi = {
  getTree: (responseId: string) => httpClient.get<DocsTreeNode>(`/rest/responses/${responseId}/docs/tree/`),
  getFile: (responseId: string, path: string) =>
    httpClient.get<DocsFileResponse>(`/rest/responses/${responseId}/docs/file/`, { query: { path } }),
};
