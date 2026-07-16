import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button } from "../../shared/ui/button";
import { Card } from "../../shared/ui/card";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { Spinner } from "../../shared/ui/spinner";
import { getLastResponseId, setLastResponseId } from "../../shared/storage/recent-response";
import { useDocsFile, useDocsTree } from "./hooks";
import { FileTree } from "./file-tree";
import { FileViewer } from "./file-viewer";
import styles from "./docs-page.module.css";

export function DocsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const responseId = searchParams.get("responseId") ?? getLastResponseId() ?? undefined;
  const activePath = searchParams.get("path") ?? undefined;

  const [responseIdInput, setResponseIdInput] = useState("");

  const tree = useDocsTree(responseId);
  const file = useDocsFile(responseId, activePath);

  if (!responseId) {
    return (
      <div>
        <h1>Docs</h1>
        <Card title="Укажите run">
          <p>Чтобы открыть документацию, укажите response_id завершённого запуска init_arch.</p>
          <div className={styles.responseIdForm}>
            <input value={responseIdInput} onChange={(event) => setResponseIdInput(event.target.value)} placeholder="response_id" />
            <Button
              variant="primary"
              onClick={() => {
                if (!responseIdInput.trim()) return;
                setLastResponseId(responseIdInput.trim());
                setSearchParams({ responseId: responseIdInput.trim() });
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
      <h1>Docs</h1>
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
