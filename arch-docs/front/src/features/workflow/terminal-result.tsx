import { Link } from "react-router-dom";
import type { ResponseStatusResponse } from "../../shared/api/models";
import { Card } from "../../shared/ui/card";
import { StatusBadge } from "../../shared/ui/status-badge";
import { responseStatusLabel, toneFromResponseStatus } from "../../shared/status/status-mapping";
import { setLastResponseId } from "../../shared/storage/recent-response";
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
          to={`/docs?responseId=${encodeURIComponent(response.response_id)}`}
          onClick={() => setLastResponseId(response.response_id)}
        >
          Открыть документацию
        </Link>
      )}
    </Card>
  );
}
