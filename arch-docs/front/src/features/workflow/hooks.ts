import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { workflowApi } from "../../shared/api/endpoints";
import type { InitArchInput } from "../../shared/api/models";

const INIT_ARCH_WORKFLOW_TYPE = "init_arch";

export const workflowQueryKeys = {
  conversation: (conversationId: string) => ["workflow", "conversation", conversationId] as const,
  items: (conversationId: string) => ["workflow", "conversation-items", conversationId] as const,
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

export function useConversationItems(conversationId: string | undefined) {
  return useQuery({
    queryKey: workflowQueryKeys.items(conversationId ?? "none"),
    queryFn: () => workflowApi.listItems(conversationId!),
    enabled: conversationId !== undefined,
  });
}

export function useCreateConversation() {
  return useMutation({ mutationFn: workflowApi.createConversation });
}

export function useCreateInitArchResponse() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: { conversationId: string; input: InitArchInput }) =>
      workflowApi.createResponse({ conversationId: params.conversationId, workflowType: INIT_ARCH_WORKFLOW_TYPE, input: params.input }),
    onSuccess: (_data, params) => queryClient.invalidateQueries({ queryKey: workflowQueryKeys.conversation(params.conversationId) }),
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
    onSuccess: () => {
      if (conversationId) queryClient.invalidateQueries({ queryKey: workflowQueryKeys.conversation(conversationId) });
    },
  });
}
