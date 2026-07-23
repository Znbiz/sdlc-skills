import { useParams, useSearchParams } from "react-router-dom";
import { Card } from "../../shared/ui/card";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { ResizableColumns } from "../../shared/ui/resizable-columns";
import { Spinner } from "../../shared/ui/spinner";
import { getProjectColumnWidths, setProjectColumnWidths } from "../../shared/storage/project-columns";
import { FileViewer } from "../docs/file-viewer";
import { useConversation, useConversationWorkspaceFile, useResponse } from "./hooks";
import { ConversationRepositories, type RunRepositoriesContext } from "./conversation-repositories";
import { ProjectTitle } from "./project-title";
import { ProjectWorkspaceTree } from "./project-workspace-tree";
import { WorkflowRunPanel } from "./workflow-run-panel";
import styles from "./project-page.module.css";

const DEFAULT_COLUMN_WIDTHS: [number, number] = [300, 380];

export function ProjectPage() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const conversation = useConversation(conversationId);

  const activePath = searchParams.get("path");
  const selectedResponseId = searchParams.get("run");

  const file = useConversationWorkspaceFile(conversationId, activePath ?? undefined);
  const selectedResponse = useResponse(selectedResponseId ?? undefined);

  if (!conversationId) return <ErrorBanner error={new Error("conversationId не указан")} />;
  if (conversation.isPending) return <Spinner label="Загрузка проекта…" />;
  if (conversation.isError) return <ErrorBanner error={conversation.error} onRetry={() => conversation.refetch()} />;

  const runRepositoriesContext: RunRepositoriesContext | null = selectedResponse.data
    ? {
        responseId: selectedResponse.data.response_id,
        editable: selectedResponse.data.repository_list_editable,
        repositories: selectedResponse.data.repositories,
      }
    : null;

  const selectPath = (path: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("path", path);
    setSearchParams(next);
  };

  const handlePathDeleted = (deletedPath: string) => {
    if (!activePath || (activePath !== deletedPath && !activePath.startsWith(`${deletedPath}/`))) return;
    const next = new URLSearchParams(searchParams);
    next.delete("path");
    setSearchParams(next);
  };

  const selectResponse = (responseId: string | null) => {
    const next = new URLSearchParams(searchParams);
    if (responseId) next.set("run", responseId);
    else next.delete("run");
    setSearchParams(next);
  };

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <ProjectTitle conversationId={conversationId} productName={conversation.data?.product_name ?? null} />
        <span className={styles.conversationId}>{conversationId}</span>
      </div>

      <ResizableColumns
        defaultWidths={getProjectColumnWidths() ?? DEFAULT_COLUMN_WIDTHS}
        onWidthsCommit={setProjectColumnWidths}
        columns={[
          <>
            <ProjectWorkspaceTree
              conversationId={conversationId}
              activePath={activePath}
              onSelect={selectPath}
              onDeleted={handlePathDeleted}
            />
            <ConversationRepositories conversationId={conversationId} run={runRepositoriesContext} />
          </>,
          <Card title="Содержимое">
            {!activePath && <p className={styles.hint}>Выберите файл в дереве слева.</p>}
            {activePath && file.isPending && <Spinner label="Загрузка файла…" />}
            {activePath && file.isError && <ErrorBanner error={file.error} onRetry={() => file.refetch()} />}
            {activePath && file.data && <FileViewer file={file.data} />}
          </Card>,
          <WorkflowRunPanel
            conversationId={conversationId}
            selectedResponseId={selectedResponseId}
            onSelectResponse={selectResponse}
          />,
        ]}
      />
    </div>
  );
}
