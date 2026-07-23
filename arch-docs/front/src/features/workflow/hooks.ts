import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { conversationsApi, workflowApi, workspaceApi } from "../../shared/api/endpoints";
import type { InitArchInput } from "../../shared/api/models";
import { INIT_ARCH_WORKFLOW_TYPE } from "./workflow-types";

export const workflowQueryKeys = {
  list: () => ["workflow", "conversations"] as const,
  conversation: (conversationId: string) => ["workflow", "conversation", conversationId] as const,
  items: (conversationId: string) => ["workflow", "conversation-items", conversationId] as const,
  repositories: (conversationId: string) => ["workflow", "conversation-repositories", conversationId] as const,
  responses: (conversationId: string) => ["workflow", "conversation-responses", conversationId] as const,
  response: (responseId: string) => ["workflow", "response", responseId] as const,
  responseItems: (responseId: string) => ["workflow", "response-items", responseId] as const,
  workspaceTree: (conversationId: string) => ["workflow", "workspace-tree", conversationId] as const,
  workspaceFile: (conversationId: string, path: string) => ["workflow", "workspace-file", conversationId, path] as const,
};

export function useConversation(conversationId: string | undefined) {
  return useQuery({
    queryKey: workflowQueryKeys.conversation(conversationId ?? "none"),
    queryFn: () => workflowApi.getConversation(conversationId!),
    enabled: conversationId !== undefined,
    refetchInterval: (query) => {
      const responseStatus = query.state.data?.active_response?.response_status;
      return responseStatus === "running" ? 4000 : false;
    },
  });
}

export function useConversations() {
  return useQuery({
    queryKey: workflowQueryKeys.list(),
    queryFn: () => workflowApi.listConversations(),
    refetchInterval: (query) => {
      const hasRunning = query.state.data?.some((conversation) => conversation.active_response?.response_status === "running");
      return hasRunning ? 4000 : 10000;
    },
  });
}

export function useConversationItems(conversationId: string | undefined) {
  return useQuery({
    queryKey: workflowQueryKeys.items(conversationId ?? "none"),
    queryFn: () => workflowApi.listItems(conversationId!),
    enabled: conversationId !== undefined,
  });
}

export function useCreateConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: workflowApi.createConversation,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: workflowQueryKeys.list() }),
  });
}

export function useCreateInitArchResponse() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: { conversationId: string; input: InitArchInput }) =>
      workflowApi.createResponse({ conversationId: params.conversationId, workflowType: INIT_ARCH_WORKFLOW_TYPE, input: params.input }),
    onSuccess: (_data, params) => {
      queryClient.invalidateQueries({ queryKey: workflowQueryKeys.conversation(params.conversationId) });
      queryClient.invalidateQueries({ queryKey: workflowQueryKeys.responses(params.conversationId) });
      queryClient.invalidateQueries({ queryKey: workflowQueryKeys.list() });
    },
  });
}

export function useSubmitResponseAction(conversationId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: {
      responseId: string;
      actionType: string;
      questionId?: string | null;
      answer?: string | null;
      field?: string | null;
      value?: unknown;
    }) => workflowApi.submitAction(params.responseId, params),
    onSuccess: (_data, params) => {
      queryClient.invalidateQueries({ queryKey: workflowQueryKeys.response(params.responseId) });
      if (conversationId) {
        queryClient.invalidateQueries({ queryKey: workflowQueryKeys.conversation(conversationId) });
        queryClient.invalidateQueries({ queryKey: workflowQueryKeys.responses(conversationId) });
        queryClient.invalidateQueries({ queryKey: workflowQueryKeys.repositories(conversationId) });
      }
      queryClient.invalidateQueries({ queryKey: workflowQueryKeys.list() });
    },
  });
}

export function useResponse(responseId: string | undefined) {
  return useQuery({
    queryKey: workflowQueryKeys.response(responseId ?? "none"),
    queryFn: () => workflowApi.getResponse(responseId!),
    enabled: responseId !== undefined,
    refetchInterval: (query) => (query.state.data?.response_status === "running" ? 4000 : false),
  });
}

export function useResponseItems(responseId: string | undefined) {
  return useQuery({
    queryKey: workflowQueryKeys.responseItems(responseId ?? "none"),
    queryFn: () => workflowApi.listResponseItems(responseId!),
    enabled: responseId !== undefined,
  });
}

export function useConversationResponses(conversationId: string | undefined) {
  return useQuery({
    queryKey: workflowQueryKeys.responses(conversationId ?? "none"),
    queryFn: () => conversationsApi.listResponses(conversationId!),
    enabled: conversationId !== undefined,
    refetchInterval: (query) => (query.state.data?.some((response) => response.response_status === "running") ? 4000 : false),
  });
}

export function useConversationRepositories(conversationId: string | undefined) {
  return useQuery({
    queryKey: workflowQueryKeys.repositories(conversationId ?? "none"),
    queryFn: () => conversationsApi.getRepositories(conversationId!),
    enabled: conversationId !== undefined,
  });
}

export function useAddConversationRepository(conversationId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (entry: string) => conversationsApi.addRepository(conversationId, entry),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: workflowQueryKeys.repositories(conversationId) });
      // `useConversation()` embeds its own `repositories` snapshot (used e.g. by InitArchForm's
      // read-only preview) - a separate query key from `workflowQueryKeys.repositories()` above,
      // so it needs its own invalidation or it goes stale after an add/remove.
      queryClient.invalidateQueries({ queryKey: workflowQueryKeys.conversation(conversationId) });
      queryClient.invalidateQueries({ queryKey: workflowQueryKeys.list() });
    },
  });
}

export function useRemoveConversationRepository(conversationId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (repositoryName: string) => conversationsApi.removeRepository(conversationId, repositoryName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: workflowQueryKeys.repositories(conversationId) });
      queryClient.invalidateQueries({ queryKey: workflowQueryKeys.conversation(conversationId) });
      queryClient.invalidateQueries({ queryKey: workflowQueryKeys.list() });
    },
  });
}

export function useUpdateProductName(conversationId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (productName: string) => conversationsApi.updateProductName(conversationId, productName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: workflowQueryKeys.conversation(conversationId) });
      queryClient.invalidateQueries({ queryKey: workflowQueryKeys.list() });
    },
  });
}

export function useDeleteConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (conversationId: string) => conversationsApi.deleteConversation(conversationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: workflowQueryKeys.list() });
    },
  });
}

export function useConversationWorkspaceTree(conversationId: string | undefined) {
  return useQuery({
    queryKey: workflowQueryKeys.workspaceTree(conversationId ?? "none"),
    queryFn: () => workspaceApi.getTree(conversationId!),
    enabled: conversationId !== undefined,
  });
}

export function useConversationWorkspaceFile(conversationId: string | undefined, path: string | undefined) {
  return useQuery({
    queryKey: workflowQueryKeys.workspaceFile(conversationId ?? "none", path ?? "none"),
    queryFn: () => workspaceApi.getFile(conversationId!, path!),
    enabled: conversationId !== undefined && path !== undefined,
  });
}
