import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { cliAuthApi, gitCredentialsApi } from "../../shared/api/endpoints";
import type { CliEngine } from "../../shared/api/models";

export const setupQueryKeys = {
  cliAuthStatus: ["setup", "cli-auth-status"] as const,
  gitStatus: ["setup", "git-status"] as const,
  authSession: (authSessionId: string) => ["setup", "auth-session", authSessionId] as const,
};

export function useCliAuthStatus() {
  return useQuery({
    queryKey: setupQueryKeys.cliAuthStatus,
    queryFn: cliAuthApi.getStatus,
    refetchInterval: 5000,
  });
}

export function useGitCredentialsStatus() {
  return useQuery({
    queryKey: setupQueryKeys.gitStatus,
    queryFn: gitCredentialsApi.getStatus,
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

export function useSetGitToken() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: gitCredentialsApi.setToken,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: setupQueryKeys.gitStatus }),
  });
}

export function useDeleteGitToken() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: gitCredentialsApi.deleteToken,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: setupQueryKeys.gitStatus }),
  });
}

export function useCheckGitAccess() {
  return useMutation({
    mutationFn: gitCredentialsApi.checkAccess,
  });
}
