import { Link } from "react-router-dom";
import type { ResponseStatusResponse } from "../../shared/api/models";
import { Card } from "../../shared/ui/card";
import { StatusBadge } from "../../shared/ui/status-badge";
import { responseStatusLabel, toneFromResponseStatus } from "../../shared/status/status-mapping";
import { setLastConversationId } from "../../shared/storage/recent-conversation";
import styles from "./terminal-result.module.css";

export function TerminalResult({ response }: { response: ResponseStatusResponse }) {
  const tone = toneFromResponseStatus(response.response_status, false);
  const canOpenDocs = response.response_status === "success" && Boolean(response.arch_repo_dir);

  return (
    <Card title="Итог запуска">
      <StatusBadge tone={tone} label={responseStatusLabel(response.response_status)} />
      {response.error_message && <p>{response.error_message}</p>}
      <dl>
        <dt>Репозиторий</dt>
        <dd>{response.current_repo_name || "—"}</dd>
        <dt>Каталог arch-репозитория</dt>
        <dd>{response.arch_repo_dir || "—"}</dd>
      </dl>
      {canOpenDocs && (
        <Link
          className={styles.docsLink}
          to={`/docs?conversationId=${encodeURIComponent(response.conversation_id)}`}
          onClick={() => setLastConversationId(response.conversation_id)}
        >
          Открыть документацию
        </Link>
      )}
    </Card>
  );
}
