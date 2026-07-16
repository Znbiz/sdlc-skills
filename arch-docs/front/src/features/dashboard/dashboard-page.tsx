import { Link } from "react-router-dom";
import { useCliAuthStatus } from "../setup/hooks";
import { useConversation } from "../workflow/hooks";
import { getLastConversationId } from "../../shared/storage/recent-conversation";
import { Card } from "../../shared/ui/card";
import { Spinner } from "../../shared/ui/spinner";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { StatusBadge } from "../../shared/ui/status-badge";
import { responseStatusLabel, toneFromResponseStatus } from "../../shared/status/status-mapping";
import styles from "./dashboard-page.module.css";

export function DashboardPage() {
  const cliAuthStatus = useCliAuthStatus();
  const lastConversationId = getLastConversationId() ?? undefined;
  const conversation = useConversation(lastConversationId);

  const readinessReady =
    cliAuthStatus.data?.codex.authenticated === true && cliAuthStatus.data?.claude.authenticated === true;

  return (
    <div className={styles.page}>
      <h1>Обзор</h1>

      <Card title="Готовность среды">
        {cliAuthStatus.isPending && <Spinner />}
        {cliAuthStatus.isError && <ErrorBanner error={cliAuthStatus.error} onRetry={() => cliAuthStatus.refetch()} />}
        {cliAuthStatus.data && (
          <StatusBadge tone={readinessReady ? "completed" : "needs_action"} label={readinessReady ? "Готово к запуску" : "Нужна донастройка"} />
        )}
        <Link className={styles.link} to="/setup">
          Перейти к Setup
        </Link>
      </Card>

      <Card title="Последний запуск">
        {!lastConversationId && <p className={styles.empty}>Ещё не было запусков init_arch.</p>}
        {lastConversationId && conversation.isPending && <Spinner />}
        {lastConversationId && conversation.data?.active_response && (
          <StatusBadge
            tone={toneFromResponseStatus(conversation.data.active_response.response_status, conversation.data.active_response.required_actions.length > 0)}
            label={responseStatusLabel(conversation.data.active_response.response_status)}
          />
        )}
        {lastConversationId && (
          <Link className={styles.link} to={`/workflows/init/${lastConversationId}`}>
            Открыть workflow
          </Link>
        )}
      </Card>

      <div className={styles.quickActions}>
        <Link className={styles.actionButton} to="/workflows/init">
          Start init
        </Link>
        <Link className={styles.actionButton} to="/docs">
          Open docs
        </Link>
      </div>
    </div>
  );
}
