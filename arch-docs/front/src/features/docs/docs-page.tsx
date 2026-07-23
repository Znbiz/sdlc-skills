import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Button } from "../../shared/ui/button";
import { Card } from "../../shared/ui/card";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { Spinner } from "../../shared/ui/spinner";
import { getLastConversationId, setLastConversationId } from "../../shared/storage/recent-conversation";
import { useConversations, useConversationWorkspaceFile, useConversationWorkspaceTree } from "../workflow/hooks";
import { FileTree } from "./file-tree";
import { FileViewer } from "./file-viewer";
import styles from "./docs-page.module.css";

function ProjectTabs({ activeConversationId, onSelect }: { activeConversationId?: string; onSelect: (conversationId: string) => void }) {
  const conversations = useConversations();
  const projects = conversations.data ?? [];

  if (conversations.isPending) return <Spinner label="Загрузка проектов…" />;
  if (conversations.isError) return null;
  if (projects.length === 0) return null;

  return (
    <div className={styles.projectTabs} role="tablist" aria-label="Проекты">
      {projects.map((conversation) => {
        const isActive = conversation.conversation_id === activeConversationId;
        return (
          <button
            key={conversation.conversation_id}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={isActive ? `${styles.projectTab} ${styles.projectTabActive}` : styles.projectTab}
            onClick={() => onSelect(conversation.conversation_id)}
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
  const conversationId = searchParams.get("conversationId") ?? getLastConversationId() ?? undefined;
  const activePath = searchParams.get("path") ?? undefined;

  const [conversationIdInput, setConversationIdInput] = useState("");

  const tree = useConversationWorkspaceTree(conversationId);
  const file = useConversationWorkspaceFile(conversationId, activePath);

  const openConversation = (id: string) => {
    setLastConversationId(id);
    setSearchParams({ conversationId: id });
  };

  if (!conversationId) {
    return (
      <div className={styles.page}>
        <h1>Документация</h1>
        <ProjectTabs activeConversationId={conversationId} onSelect={openConversation} />
        <Card title="Выберите проект">
          <p>Чтобы открыть документацию, укажите id проекта.</p>
          <div className={styles.conversationIdForm}>
            <input value={conversationIdInput} onChange={(event) => setConversationIdInput(event.target.value)} placeholder="id проекта" />
            <Button
              variant="primary"
              onClick={() => {
                if (!conversationIdInput.trim()) return;
                openConversation(conversationIdInput.trim());
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
    next.set("conversationId", conversationId);
    next.set("path", path);
    setSearchParams(next);
  };

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1>Документация</h1>
        <Link to="/projects" className={styles.allProjectsLink}>
          Все проекты →
        </Link>
      </div>
      <ProjectTabs activeConversationId={conversationId} onSelect={openConversation} />
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
