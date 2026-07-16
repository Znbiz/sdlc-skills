import { useQuery } from "@tanstack/react-query";
import { docsApi } from "../../shared/api/endpoints";

export function useDocsTree(responseId: string | undefined) {
  return useQuery({
    queryKey: ["docs", "tree", responseId ?? "none"],
    queryFn: () => docsApi.getTree(responseId!),
    enabled: responseId !== undefined,
  });
}

export function useDocsFile(responseId: string | undefined, path: string | undefined) {
  return useQuery({
    queryKey: ["docs", "file", responseId ?? "none", path ?? "none"],
    queryFn: () => docsApi.getFile(responseId!, path!),
    enabled: responseId !== undefined && path !== undefined,
  });
}
