import { Card } from "../../shared/ui/card";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { Spinner } from "../../shared/ui/spinner";
import { FileTree } from "../docs/file-tree";
import { useConversationWorkspaceTree } from "./hooks";

export function ProjectWorkspaceTree({
  conversationId,
  activePath,
  onSelect,
}: {
  conversationId: string;
  activePath: string | null;
  onSelect: (path: string) => void;
}) {
  const tree = useConversationWorkspaceTree(conversationId);

  return (
    <Card title="Файлы проекта">
      {tree.isPending && <Spinner label="Загрузка дерева…" />}
      {tree.isError && <ErrorBanner error={tree.error} onRetry={() => tree.refetch()} />}
      {tree.data && <FileTree root={tree.data} activePath={activePath} onSelect={onSelect} />}
    </Card>
  );
}
