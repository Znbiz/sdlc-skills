import { useCallback, useReducer } from "react";
import { useParams } from "react-router-dom";
import { Button } from "../../shared/ui/button";
import { Card } from "../../shared/ui/card";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { Spinner } from "../../shared/ui/spinner";
import { StatusBadge } from "../../shared/ui/status-badge";
import { useEventSource } from "../../shared/sse/use-event-source";
import { workflowApi } from "../../shared/api/endpoints";
import { toneFromResponseStatus, responseStatusLabel } from "../../shared/status/status-mapping";
import { useConversation, useConversationItems, useCreateInitArchResponse, useSubmitResponseAction } from "./hooks";
import { INITIAL_STREAM_STATE, reduceStreamEvent } from "./stream-events";
import { Timeline } from "./timeline";
import { RequiredActionCard } from "./required-action-card";
import { TerminalResult } from "./terminal-result";
import { InitArchForm } from "./init-arch-form";
import styles from "./init-workflow-page.module.css";

export function InitWorkflowPage() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const conversation = useConversation(conversationId);
  const items = useConversationItems(conversationId);
  const createResponse = useCreateInitArchResponse();
  const submitAction = useSubmitResponseAction(conversationId);

  const [streamState, dispatch] = useReducer(reduceStreamEvent, INITIAL_STREAM_STATE);

  const activeResponse = conversation.data?.active_response ?? null;
  const isStreamable = activeResponse !== null && activeResponse.response_status === "running";

  const onMessage = useCallback((event: MessageEvent<string>) => {
    try {
      const payload = JSON.parse(event.data) as Record<string, unknown>;
      dispatch(payload);
    } catch {
      // событие не в ожидаемом формате — игнорируем, snapshot остаётся источником истины
    }
  }, []);

  const streamUrl = conversationId ? workflowApi.conversationStreamUrl(conversationId) : null;
  const connectionState = useEventSource(isStreamable ? streamUrl : null, {
    onMessage,
    onReconnect: () => conversation.refetch(),
  });

  if (!conversationId) return <ErrorBanner error={new Error("conversationId не указан")} />;
  if (conversation.isPending) return <Spinner label="Загрузка conversation…" />;
  if (conversation.isError) return <ErrorBanner error={conversation.error} onRetry={() => conversation.refetch()} />;

  return (
    <div className={styles.page}>
      <h1>Init Workflow</h1>

      {!activeResponse && (
        <Card title="Запуск init_arch">
          <InitArchForm
            isSubmitting={createResponse.isPending}
            onSubmit={(input) => createResponse.mutate({ conversationId, input })}
          />
          {createResponse.isError && <ErrorBanner error={createResponse.error} />}
        </Card>
      )}

      {activeResponse && (
        <>
          <Card title="Текущий статус">
            <div className={styles.statusRow}>
              <StatusBadge
                tone={toneFromResponseStatus(activeResponse.response_status, activeResponse.required_actions.length > 0)}
                label={responseStatusLabel(activeResponse.response_status)}
              />
              <span>Шаг: {streamState.currentStepLabel || activeResponse.current_step_id || "—"}</span>
              <span>Репозиторий: {streamState.currentRepoName || activeResponse.current_repo_name || "—"}</span>
              {connectionState === "reconnecting" && <span className={styles.degraded}>соединение прервано, переподключаемся…</span>}
              {activeResponse.response_status === "running" && (
                <Button
                  variant="secondary"
                  disabled={submitAction.isPending}
                  onClick={() => submitAction.mutate({ responseId: activeResponse.response_id, actionType: "pause" })}
                >
                  Остановить
                </Button>
              )}
            </div>
            {submitAction.isError && <ErrorBanner error={submitAction.error} onRetry={() => {}} />}
          </Card>

          {activeResponse.response_status === "paused" && (
            <Card title="Workflow на паузе">
              <p>
                Остановлен на шаге: {streamState.currentStepLabel || activeResponse.current_step_id || "—"}
                {(streamState.currentRepoName || activeResponse.current_repo_name) &&
                  ` (${streamState.currentRepoName || activeResponse.current_repo_name})`}
                . Прогресс сохранён — продолжение начнётся с этого шага.
              </p>
              <Button
                variant="primary"
                disabled={submitAction.isPending}
                onClick={() => submitAction.mutate({ responseId: activeResponse.response_id, actionType: "continue" })}
              >
                Продолжить
              </Button>
            </Card>
          )}

          {activeResponse.required_actions.map((action, index) => (
            <RequiredActionCard
              key={action.question_id ?? `${action.action_type}-${index}`}
              responseId={activeResponse.response_id}
              conversationId={conversationId}
              action={action}
            />
          ))}

          {activeResponse.response_status !== "success" && activeResponse.response_status !== "failed" && (
            <Card title="Поток событий">
              {streamState.entries.length === 0 ? (
                <p className={styles.empty}>Событий пока нет.</p>
              ) : (
                <div className={styles.streamLog}>
                  {streamState.entries.map((entry, index) => (
                    <div key={`${entry.eventType}-${index}`} className={`${styles.streamEntry} ${styles[`actor-${entry.actor}`]}`}>
                      <span className={styles.actorBadge}>{entry.actor}</span>
                      <span className={styles.streamMessage}>{entry.message}</span>
                      {entry.detail && (
                        <details className={styles.streamDetail}>
                          <summary>подробнее</summary>
                          <pre>{entry.detail}</pre>
                        </details>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Card>
          )}

          {(activeResponse.response_status === "success" || activeResponse.response_status === "failed") && (
            <TerminalResult response={activeResponse} />
          )}

          <Card title="Timeline">
            {items.isPending && <Spinner label="Загрузка timeline…" />}
            {items.isError && <ErrorBanner error={items.error} onRetry={() => items.refetch()} />}
            {items.data && <Timeline items={items.data.items} />}
          </Card>
        </>
      )}
    </div>
  );
}
