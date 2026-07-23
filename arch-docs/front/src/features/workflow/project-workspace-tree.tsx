import { Card } from "../../shared/ui/card";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { Spinner } from "../../shared/ui/spinner";
import type { DocsTreeNode } from "../../shared/api/models";
import { FileTree } from "../docs/file-tree";
import { useConversationWorkspaceTree, useDeleteConversationWorkspacePath } from "./hooks";

export function ProjectWorkspaceTree({
  conversationId,
  activePath,
  onSelect,
  onDeleted,
}: {
  conversationId: string;
  activePath: string | null;
  onSelect: (path: string) => void;
  onDeleted: (deletedPath: string) => void;
}) {
  const tree = useConversationWorkspaceTree(conversationId);
  const deletePath = useDeleteConversationWorkspacePath(conversationId);

  const handleDelete = (node: DocsTreeNode) => {
    const kind = node.node_type === "directory" ? "папку" : "файл";
    if (!window.confirm(`Удалить ${kind} «${node.path}»? Это действие необратимо.`)) return;
    deletePath.mutate(node.path, { onSuccess: () => onDeleted(node.path) });
  };

  return (
    <Card title="Файлы проекта">
      {tree.isPending && <Spinner label="Загрузка дерева…" />}
      {tree.isError && <ErrorBanner error={tree.error} onRetry={() => tree.refetch()} />}
      {deletePath.isError && <ErrorBanner error={deletePath.error} onRetry={() => deletePath.reset()} />}
      {tree.data && <FileTree root={tree.data} activePath={activePath} onSelect={onSelect} onDelete={handleDelete} />}
    </Card>
  );
}
