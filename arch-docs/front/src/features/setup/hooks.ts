import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { cliAuthApi, gitConnectionsApi, gitSshApi, llmProvidersApi } from "../../shared/api/endpoints";
import type { LlmProviderConnectionParams } from "../../shared/api/endpoints";
import type { CliEngine, GitConnectionType } from "../../shared/api/models";

export const setupQueryKeys = {
  cliAuthStatus: ["setup", "cli-auth-status"] as const,
  gitConnections: ["setup", "git-connections"] as const,
  gitConnection: (connectionId: string) => ["setup", "git-connections", connectionId] as const,
  gitSshPublicKey: ["setup", "git-ssh-public-key"] as const,
  authSession: (authSessionId: string) => ["setup", "auth-session", authSessionId] as const,
  llmProviderConnections: ["setup", "llm-provider-connections"] as const,
  llmProviderConnection: (connectionId: string) => ["setup", "llm-provider-connections", connectionId] as const,
};

export function useCliAuthStatus() {
  return useQuery({
    queryKey: setupQueryKeys.cliAuthStatus,
    queryFn: cliAuthApi.getStatus,
    refetchInterval: 5000,
  });
}

export function useGitConnections() {
  return useQuery({
    queryKey: setupQueryKeys.gitConnections,
    queryFn: gitConnectionsApi.list,
  });
}

export function useGitConnection(connectionId: string | null) {
  return useQuery({
    queryKey: setupQueryKeys.gitConnection(connectionId ?? "none"),
    queryFn: () => gitConnectionsApi.get(connectionId!),
    enabled: connectionId !== null,
  });
}

export function useAuthSession(authSessionId: string | null) {
  return useQuery({
    queryKey: setupQueryKeys.authSession(authSessionId ?? "none"),
    queryFn: () => cliAuthApi.getAuthSession(authSessionId!),
    enabled: authSessionId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.auth_flow_status;
      return status === "pending" ? 3000 : false;
    },
  });
}

export function useInitAuth() {
  return useMutation({
    mutationFn: (cliEngine: CliEngine) => cliAuthApi.initAuth(cliEngine),
  });
}

export function useSubmitAuthCode() {
  return useMutation({
    mutationFn: (params: { authSessionId: string; code: string }) => cliAuthApi.submitAuthCode(params.authSessionId, params.code),
  });
}

export function useCreateGitConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: { host: string; connectionType: GitConnectionType; token?: string; username?: string }) =>
      gitConnectionsApi.create(params),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: setupQueryKeys.gitConnections }),
  });
}

export function useUpdateGitConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: {
      connectionId: string;
      host: string;
      connectionType: GitConnectionType;
      token?: string;
      username?: string;
    }) => gitConnectionsApi.update(params.connectionId, params),
    onSuccess: (_data, params) => {
      queryClient.invalidateQueries({ queryKey: setupQueryKeys.gitConnections });
      queryClient.invalidateQueries({ queryKey: setupQueryKeys.gitConnection(params.connectionId) });
    },
  });
}

export function useDeleteGitConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: gitConnectionsApi.delete,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: setupQueryKeys.gitConnections }),
  });
}

export function useGitSshPublicKey() {
  return useQuery({
    queryKey: setupQueryKeys.gitSshPublicKey,
    queryFn: gitSshApi.getPublicKey,
  });
}

export function useLlmProviderConnections() {
  return useQuery({
    queryKey: setupQueryKeys.llmProviderConnections,
    queryFn: llmProvidersApi.list,
  });
}

export function useLlmProviderConnection(connectionId: string | null) {
  return useQuery({
    queryKey: setupQueryKeys.llmProviderConnection(connectionId ?? "none"),
    queryFn: () => llmProvidersApi.get(connectionId!),
    enabled: connectionId !== null,
  });
}

export function useCreateLlmProviderConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: LlmProviderConnectionParams) => llmProvidersApi.create(params),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: setupQueryKeys.llmProviderConnections }),
  });
}

export function useUpdateLlmProviderConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: { connectionId: string } & LlmProviderConnectionParams) =>
      llmProvidersApi.update(params.connectionId, params),
    onSuccess: (_data, params) => {
      queryClient.invalidateQueries({ queryKey: setupQueryKeys.llmProviderConnections });
      queryClient.invalidateQueries({ queryKey: setupQueryKeys.llmProviderConnection(params.connectionId) });
    },
  });
}

export function useDeleteLlmProviderConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: llmProvidersApi.delete,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: setupQueryKeys.llmProviderConnections }),
  });
}

export function useTestLlmProviderConnection() {
  return useMutation({
    mutationFn: (connectionId: string) => llmProvidersApi.test(connectionId),
  });
}
