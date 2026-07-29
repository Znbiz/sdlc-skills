import { useCallback, useEffect, useReducer, useState } from "react";
import { Button } from "../../shared/ui/button";
import { Card } from "../../shared/ui/card";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { Modal } from "../../shared/ui/modal";
import { Spinner } from "../../shared/ui/spinner";
import { StatusBadge } from "../../shared/ui/status-badge";
import { ApiError } from "../../shared/api/http-client";
import { useEventSource } from "../../shared/sse/use-event-source";
import { workflowApi } from "../../shared/api/endpoints";
import type { TokenUsage } from "../../shared/api/models";
import { toneFromResponseStatus, responseStatusLabel } from "../../shared/status/status-mapping";
import { formatDateTime } from "../../shared/format/format";
import {
  useConversation,
  useConversationResponses,
  useCreateInitArchResponse,
  useResponse,
  useResponseItems,
  useSubmitResponseAction,
} from "./hooks";
import { INITIAL_STREAM_STATE, reduceStreamEvent, type TokenUsageEntry } from "./stream-events";
import { resolveActiveGraphNodeId, WorkflowGraphView } from "./workflow-graph";
import { Timeline } from "./timeline";
import { RequiredActionCard } from "./required-action-card";
import { QueuedQuestionsCard } from "./queued-questions-card";
import { TerminalResult } from "./terminal-result";
import { InitArchForm } from "./init-arch-form";
import { INIT_ARCH_WORKFLOW_TYPE, WORKFLOW_TYPE_OPTIONS } from "./workflow-types";
import styles from "./workflow-run-panel.module.css";

const ACTIVE_STATUSES = new Set(["running", "paused", "interrupted"]);

export function restTokenUsageToView(usage: Record<string, TokenUsage>): Record<string, TokenUsageEntry> {
  const view: Record<string, TokenUsageEntry> = {};
  for (const [modelName, tokens] of Object.entries(usage)) {
    view[modelName] = { inputTokens: tokens.input_tokens, outputTokens: tokens.output_tokens };
  }
  return view;
}

// Tokens only ever increase within a run, so a per-model max is a safe way to combine the two
// independent sources: the SSE stream (updates fast but can miss an event across a reconnect gap,
// since the live bus doesn't replay history - see _stream_live_workflow_events) and the REST poll
// (always correct since the backend persists usage before publishing the SSE event, but only
// refetches every 4s). Preferring one source outright risks getting stuck on stale stream data
// after a missed reconnect event.
export function mergeTokenUsage(
  a: Record<string, TokenUsageEntry>,
  b: Record<string, TokenUsageEntry>,
): Record<string, TokenUsageEntry> {
  const merged: Record<string, TokenUsageEntry> = {};
  for (const modelName of new Set([...Object.keys(a), ...Object.keys(b)])) {
    merged[modelName] = {
      inputTokens: Math.max(a[modelName]?.inputTokens ?? 0, b[modelName]?.inputTokens ?? 0),
      outputTokens: Math.max(a[modelName]?.outputTokens ?? 0, b[modelName]?.outputTokens ?? 0),
    };
  }
  return merged;
}

export function TokenUsageStatsCard({ tokenUsageByModel }: { tokenUsageByModel: Record<string, TokenUsageEntry> }) {
  const modelNames = Object.keys(tokenUsageByModel).sort();

  return (
    <Card title="Статистика">
      {modelNames.length === 0 ? (
        <p className={styles.empty}>Данных о расходе токенов пока нет.</p>
      ) : (
        <table className={styles.tokenUsageTable}>
          <thead>
            <tr>
              <th>Модель</th>
              <th>Input</th>
              <th>Output</th>
            </tr>
          </thead>
          <tbody>
            {modelNames.map((modelName) => {
              const usage = tokenUsageByModel[modelName];
              return (
                <tr key={modelName}>
                  <td>{modelName}</td>
                  <td>{usage.inputTokens.toLocaleString("ru-RU")}</td>
                  <td>{usage.outputTokens.toLocaleString("ru-RU")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Card>
  );
}

export function WorkflowRunPanel({
  conversationId,
  selectedResponseId,
  onSelectResponse,
}: {
  conversationId: string;
  selectedResponseId: string | null;
  onSelectResponse: (responseId: string | null) => void;
}) {
  const conversation = useConversation(conversationId);
  const responses = useConversationResponses(conversationId);
  const createResponse = useCreateInitArchResponse();
  const [showNewRunForm, setShowNewRunForm] = useState(false);
  const [selectedWorkflowType, setSelectedWorkflowType] = useState(WORKFLOW_TYPE_OPTIONS[0].value);

  useEffect(() => {
    if (selectedResponseId || !responses.data || responses.data.length === 0) return;
    onSelectResponse(responses.data[0].response_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [responses.data, selectedResponseId]);

  if (conversation.isPending || responses.isPending) return <Spinner label="Загрузка workflow…" />;
  if (conversation.isError) return <ErrorBanner error={conversation.error} onRetry={() => conversation.refetch()} />;
  if (responses.isError) return <ErrorBanner error={responses.error} onRetry={() => responses.refetch()} />;

  const hasActiveRun = responses.data.some((response) => ACTIVE_STATUSES.has(response.response_status));
  const repositoryNames = conversation.data.repositories.map((repository) => repository.repository_name);
  const isLiveSelection = selectedResponseId === conversation.data.active_response?.response_id;
  const productName = conversation.data.product_name?.trim() || conversationId.slice(0, 8);

  return (
    <>
      <Card title="Workflow">
        <div className={styles.selectorRow}>
          <select
            className={styles.selector}
            aria-label="Тип workflow для запуска"
            value={selectedWorkflowType}
            disabled={WORKFLOW_TYPE_OPTIONS.length <= 1}
            onChange={(event) => setSelectedWorkflowType(event.target.value)}
          >
            {WORKFLOW_TYPE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <Button
            variant="primary"
            disabled={hasActiveRun}
            title={hasActiveRun ? "Уже есть активный прогон для этого проекта" : undefined}
            onClick={() => setShowNewRunForm((prev) => !prev)}
          >
            Запустить
          </Button>
        </div>
        {hasActiveRun && !showNewRunForm && (
          <p className={styles.empty}>Новый прогон недоступен, пока активен текущий (пауза/продолжение/restart).</p>
        )}

        {responses.data.length > 1 && (
          <div className={styles.selectorRow}>
            <select
              className={styles.selector}
              aria-label="Выбор прогона"
              value={selectedResponseId ?? ""}
              onChange={(event) => onSelectResponse(event.target.value || null)}
            >
              {responses.data.map((response) => (
                <option key={response.response_id} value={response.response_id}>
                  {responseStatusLabel(response.response_status)} · {response.current_step_id || "—"} ·{" "}
                  {new Date(response.created_at).toLocaleString("ru-RU")}
                </option>
              ))}
            </select>
          </div>
        )}
      </Card>

      {showNewRunForm && selectedWorkflowType === INIT_ARCH_WORKFLOW_TYPE && (
        <Card title="Запуск init_arch">
          <InitArchForm
            isSubmitting={createResponse.isPending}
            defaultWorkspaceDir={conversation.data.workspace_dir}
            productName={productName}
            repositoryNames={repositoryNames}
            previousInput={conversation.data.previous_init_input}
            onSubmit={(input) =>
              createResponse.mutate(
                { conversationId, input },
                {
                  onSuccess: (response) => {
                    setShowNewRunForm(false);
                    onSelectResponse(response.response_id);
                  },
                },
              )
            }
          />
          {createResponse.isError && <ErrorBanner error={createResponse.error} />}
        </Card>
      )}

      {selectedResponseId && (
        <SelectedRunPanel
          key={selectedResponseId}
          conversationId={conversationId}
          responseId={selectedResponseId}
          isLive={isLiveSelection}
          onSelectionInvalid={() => onSelectResponse(null)}
        />
      )}
    </>
  );
}

function SelectedRunPanel({
  conversationId,
  responseId,
  isLive,
  onSelectionInvalid,
}: {
  conversationId: string;
  responseId: string;
  isLive: boolean;
  onSelectionInvalid: () => void;
}) {
  const response = useResponse(responseId);
  const items = useResponseItems(responseId);
  const submitAction = useSubmitResponseAction(conversationId);
  const [showRestartConfirm, setShowRestartConfirm] = useState(false);
  const [showGraph, setShowGraph] = useState(false);
  const [streamState, dispatch] = useReducer(reduceStreamEvent, INITIAL_STREAM_STATE);

  const activeResponse = response.data ?? null;
  const isStreamable = isLive && activeResponse !== null && activeResponse.response_status === "running";

  useEffect(() => {
    // Response id can outlive its record - most commonly a `?run=` link left over from before a
    // `restart` (which deletes the WorkflowRecord). Self-heal instead of getting stuck on a 404 forever.
    if (response.isError && response.error instanceof ApiError && response.error.kind === "not_found") {
      onSelectionInvalid();
    }
  }, [response.isError, response.error, onSelectionInvalid]);

  const onMessage = useCallback((event: MessageEvent<string>) => {
    try {
      const payload = JSON.parse(event.data) as Record<string, unknown>;
      dispatch(payload);
    } catch {
      // событие не в ожидаемом формате — игнорируем, snapshot остаётся источником истины
    }
  }, []);

  const streamUrl = isLive ? workflowApi.conversationStreamUrl(conversationId) : null;
  const connectionState = useEventSource(isStreamable ? streamUrl : null, {
    onMessage,
    onReconnect: () => response.refetch(),
  });

  if (response.isPending) return <Spinner label="Загрузка прогона…" />;
  if (response.isError) return <ErrorBanner error={response.error} onRetry={() => response.refetch()} />;
  if (!activeResponse) return null;

  // Вопросы, зарегистрированные заранее (во время analyze_repositories), тоже попадают в required_actions,
  // но workflow реально приостановлен только на одном из них — том, чей payload содержит "question"
  // (пришёл из interrupt()). Остальные — просто очередь на будущее, backend пока не примет на них ответ,
  // поэтому показываем их отдельным компактным списком без формы.
  const queuedQuestions = activeResponse.required_actions.filter(
    (action) => action.action_type === "user_question" && action.payload.question === undefined,
  );
  const actionableActions = activeResponse.required_actions.filter((action) => !queuedQuestions.includes(action));

  const tokenUsageByModel = mergeTokenUsage(
    restTokenUsageToView(activeResponse.token_usage_by_model),
    streamState.tokenUsageByModel,
  );

  const activeGraphNodeId = resolveActiveGraphNodeId({
    hasStepFailedAction: activeResponse.required_actions.some((action) => action.action_type === "step_failed"),
    responseStatus: activeResponse.response_status,
    currentStepId: (isStreamable && streamState.currentStepId) || activeResponse.current_step_id,
  });

  const runContent = (
    <>
      <TokenUsageStatsCard tokenUsageByModel={tokenUsageByModel} />

      <Card title="Текущий статус">
        <div className={styles.statusRow}>
          <StatusBadge
            tone={toneFromResponseStatus(activeResponse.response_status, activeResponse.required_actions.length > 0)}
            label={responseStatusLabel(activeResponse.response_status)}
          />
          <span>Шаг: {(isStreamable && streamState.currentStepLabel) || activeResponse.current_step_id || "—"}</span>
          <span>Репозиторий: {(isStreamable && streamState.currentRepoName) || activeResponse.current_repo_name || "—"}</span>
          {isStreamable && connectionState === "reconnecting" && (
            <span className={styles.degraded}>соединение прервано, переподключаемся…</span>
          )}
          {activeResponse.response_status === "running" && (
            <Button
              variant="secondary"
              disabled={submitAction.isPending}
              onClick={() => submitAction.mutate({ responseId: activeResponse.response_id, actionType: "pause" })}
            >
              Остановить
            </Button>
          )}
          <Button variant="danger" disabled={submitAction.isPending} onClick={() => setShowRestartConfirm(true)}>
            Начать анализ заново
          </Button>
          <Button variant="secondary" onClick={() => setShowGraph(true)}>
            Показать граф
          </Button>
        </div>
        {submitAction.isError && <ErrorBanner error={submitAction.error} />}
      </Card>

      {showRestartConfirm && (
        <Card title="Начать анализ заново?">
          <p>Это действие необратимо и удалит для этого прогона:</p>
          <ul>
            <li>весь прогресс и историю (шаги, лог событий, действия);</li>
            <li>все вызовы LLM и их полный вывод.</li>
          </ul>
          <p>
            Склонированные репозитории и накопленная документация — общие артефакты проекта, их restart не
            затрагивает; они будут переиспользованы или переклонированы заново при следующем запуске.
          </p>
          <div className={styles.statusRow}>
            <Button variant="secondary" disabled={submitAction.isPending} onClick={() => setShowRestartConfirm(false)}>
              Отмена
            </Button>
            <Button
              variant="danger"
              disabled={submitAction.isPending}
              onClick={() => {
                submitAction.mutate({ responseId: activeResponse.response_id, actionType: "restart" });
                setShowRestartConfirm(false);
                onSelectionInvalid();
              }}
            >
              Да, удалить прогресс и начать заново
            </Button>
          </div>
        </Card>
      )}

      {activeResponse.response_status === "paused" && (
        <Card title="Workflow на паузе">
          <p>
            Остановлен на шаге: {activeResponse.current_step_id || "—"}
            {activeResponse.current_repo_name && ` (${activeResponse.current_repo_name})`}. Прогресс сохранён —
            продолжение начнётся с этого шага.
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

      {actionableActions.map((action, index) => (
        <RequiredActionCard
          key={action.question_id ?? `${action.action_type}-${index}`}
          responseId={activeResponse.response_id}
          conversationId={conversationId}
          action={action}
        />
      ))}

      <QueuedQuestionsCard questions={queuedQuestions} />

      {activeResponse.response_status !== "success" && activeResponse.response_status !== "failed" && (
        <Card title="Поток событий">
          {isStreamable && streamState.entries.length > 0 ? (
            <div className={styles.streamLog}>
              {streamState.entries.map((entry, index) => (
                <div key={`${entry.eventType}-${index}`} className={`${styles.streamEntry} ${styles[`actor-${entry.actor}`]}`}>
                  <span className={styles.actorBadge}>{entry.actor}</span>
                  <span className={styles.streamTime}>{formatDateTime(new Date(entry.receivedAt).toISOString())}</span>
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
          ) : (
            <p className={styles.empty}>Событий пока нет.</p>
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
  );

  return (
    <>
      {runContent}
      {showGraph && (
        <Modal title="Граф workflow" dialogClassName={styles.graphModalDialog} onClose={() => setShowGraph(false)}>
          <WorkflowGraphView
            activeNodeId={activeGraphNodeId}
            repositories={activeResponse.repositories}
            analysisWindowStart={activeResponse.analysis_window_start}
            analysisWindowEnd={activeResponse.analysis_window_end}
            analysisWindowIndex={activeResponse.analysis_window_index}
          />
          <div className={styles.graphModalBlocks}>{runContent}</div>
        </Modal>
      )}
    </>
  );
}

