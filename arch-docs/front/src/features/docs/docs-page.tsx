import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Button } from "../../shared/ui/button";
import { Card } from "../../shared/ui/card";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { Spinner } from "../../shared/ui/spinner";
import { getLastResponseId, setLastResponseId } from "../../shared/storage/recent-response";
import { useConversations } from "../workflow/hooks";
import { useDocsFile, useDocsTree } from "./hooks";
import { FileTree } from "./file-tree";
import { FileViewer } from "./file-viewer";
import styles from "./docs-page.module.css";

function ProjectTabs({ activeResponseId, onSelect }: { activeResponseId?: string; onSelect: (responseId: string) => void }) {
  const conversations = useConversations();
  const projectsWithRuns = (conversations.data ?? []).filter((conversation) => conversation.active_response !== null);

  if (conversations.isPending) return <Spinner label="Загрузка проектов…" />;
  if (conversations.isError) return null;
  if (projectsWithRuns.length === 0) return null;

  return (
    <div className={styles.projectTabs} role="tablist" aria-label="Проекты">
      {projectsWithRuns.map((conversation) => {
        const isActive = conversation.active_response!.response_id === activeResponseId;
        return (
          <button
            key={conversation.conversation_id}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={isActive ? `${styles.projectTab} ${styles.projectTabActive}` : styles.projectTab}
            onClick={() => onSelect(conversation.active_response!.response_id)}
          >
            {conversation.product_name?.trim() || conversation.conversation_id.slice(0, 8)}
          </button>
        );
      })}
    </div>
  );
}

export function DocsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const responseId = searchParams.get("responseId") ?? getLastResponseId() ?? undefined;
  const activePath = searchParams.get("path") ?? undefined;

  const [responseIdInput, setResponseIdInput] = useState("");

  const tree = useDocsTree(responseId);
  const file = useDocsFile(responseId, activePath);

  const openResponseId = (id: string) => {
    setLastResponseId(id);
    setSearchParams({ responseId: id });
  };

  if (!responseId) {
    return (
      <div className={styles.page}>
        <h1>Docs</h1>
        <ProjectTabs activeResponseId={responseId} onSelect={openResponseId} />
        <Card title="Выберите проект">
          <p>Чтобы открыть документацию, укажите response_id завершённого запуска init_arch.</p>
          <div className={styles.responseIdForm}>
            <input value={responseIdInput} onChange={(event) => setResponseIdInput(event.target.value)} placeholder="response_id" />
            <Button
              variant="primary"
              onClick={() => {
                if (!responseIdInput.trim()) return;
                openResponseId(responseIdInput.trim());
              }}
            >
              Открыть
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  const selectPath = (path: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("responseId", responseId);
    next.set("path", path);
    setSearchParams(next);
  };

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1>Docs</h1>
        <Link to="/projects" className={styles.allProjectsLink}>
          Все проекты →
        </Link>
      </div>
      <ProjectTabs activeResponseId={responseId} onSelect={openResponseId} />
      <div className={styles.layout}>
        <Card title="Дерево файлов">
          {tree.isPending && <Spinner label="Загрузка дерева…" />}
          {tree.isError && <ErrorBanner error={tree.error} onRetry={() => tree.refetch()} />}
          {tree.data && <FileTree root={tree.data} activePath={activePath ?? null} onSelect={selectPath} />}
        </Card>
        <Card title="Содержимое">
          {!activePath && <p className={styles.hint}>Выберите файл в дереве слева.</p>}
          {activePath && file.isPending && <Spinner label="Загрузка файла…" />}
          {activePath && file.isError && <ErrorBanner error={file.error} onRetry={() => file.refetch()} />}
          {activePath && file.data && <FileViewer file={file.data} />}
        </Card>
      </div>
    </div>
  );
}
