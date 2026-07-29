import { useEffect, useState } from "react";
import { Button } from "../../shared/ui/button";
import { Card } from "../../shared/ui/card";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { Modal } from "../../shared/ui/modal";
import { Spinner } from "../../shared/ui/spinner";
import type { LlmProviderConnectionSummaryResponse, LlmProviderConnectionTestResponse } from "../../shared/api/models";
import {
  useCreateLlmProviderConnection,
  useDeleteLlmProviderConnection,
  useLlmProviderConnection,
  useLlmProviderConnections,
  useTestLlmProviderConnection,
  useUpdateLlmProviderConnection,
} from "./hooks";
import styles from "./llm-providers-card.module.css";

type ModalState = { mode: "create" } | { mode: "edit"; connectionId: string; name: string };

export function LlmProvidersCard() {
  const connections = useLlmProviderConnections();
  const [modalState, setModalState] = useState<ModalState | null>(null);

  return (
    <Card title="Внешние LLM-провайдеры (OpenAI-совместимые)">
      {connections.isPending && <Spinner label="Загрузка подключений…" />}
      {connections.isError && <ErrorBanner error={connections.error} onRetry={() => connections.refetch()} />}

      {connections.data && (
        <ul className={styles.list}>
          {connections.data.length === 0 && <li className={styles.empty}>Пока нет подключённых внешних LLM</li>}
          {connections.data.map((connection) => (
            <LlmProviderConnectionRow
              key={connection.connection_id}
              connection={connection}
              onEdit={() => setModalState({ mode: "edit", connectionId: connection.connection_id, name: connection.name })}
            />
          ))}
        </ul>
      )}

      <Button variant="primary" onClick={() => setModalState({ mode: "create" })}>
        Новое подключение
      </Button>

      {modalState && <LlmProviderConnectionModal state={modalState} onClose={() => setModalState(null)} />}
    </Card>
  );
}

function LlmProviderConnectionRow({
  connection,
  onEdit,
}: {
  connection: LlmProviderConnectionSummaryResponse;
  onEdit: () => void;
}) {
  const deleteConnection = useDeleteLlmProviderConnection();
  const testConnection = useTestLlmProviderConnection();
  const [testResult, setTestResult] = useState<LlmProviderConnectionTestResponse | null>(null);

  return (
    <li className={styles.item}>
      <div className={styles.itemRow}>
        <span className={styles.name}>{connection.name}</span>
        <span className={styles.model}>{connection.model}</span>
        <div className={styles.itemActions}>
          <button
            type="button"
            className={styles.iconButton}
            disabled={testConnection.isPending}
            onClick={() => {
              setTestResult(null);
              testConnection.mutate(connection.connection_id, { onSuccess: setTestResult });
            }}
          >
            {testConnection.isPending ? "Проверка…" : "Проверить"}
          </button>
          <button type="button" className={styles.iconButton} aria-label={`Редактировать ${connection.name}`} onClick={onEdit}>
            ✎
          </button>
          <button
            type="button"
            className={styles.iconButton}
            aria-label={`Удалить ${connection.name}`}
            disabled={deleteConnection.isPending}
            onClick={() => deleteConnection.mutate(connection.connection_id)}
          >
            ×
          </button>
        </div>
      </div>

      {testConnection.isError && <ErrorBanner error={testConnection.error} onRetry={() => {}} />}
      {deleteConnection.isError && <ErrorBanner error={deleteConnection.error} onRetry={() => {}} />}
      {testResult && (
        <p className={testResult.success ? styles.testResultOk : styles.testResultFailed}>
          {testResult.success ? "✓ " : "✗ "}
          {testResult.message}
        </p>
      )}
    </li>
  );
}

function LlmProviderConnectionModal({ state, onClose }: { state: ModalState; onClose: () => void }) {
  const isEdit = state.mode === "edit";
  const existingConnectionId = isEdit ? state.connectionId : null;
  const detail = useLlmProviderConnection(existingConnectionId);
  const createConnection = useCreateLlmProviderConnection();
  const updateConnection = useUpdateLlmProviderConnection();

  const [name, setName] = useState(isEdit ? state.name : "");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [token, setToken] = useState("");
  const [wireApi, setWireApi] = useState<"chat" | "responses">("responses");
  const [prefilled, setPrefilled] = useState(!isEdit);

  useEffect(() => {
    if (isEdit && detail.data && !prefilled) {
      setName(detail.data.name);
      setBaseUrl(detail.data.base_url);
      setModel(detail.data.model);
      setWireApi(detail.data.wire_api === "chat" ? "chat" : "responses");
      setPrefilled(true);
    }
  }, [isEdit, detail.data, prefilled]);

  const mutation = isEdit ? updateConnection : createConnection;

  const submit = () => {
    const trimmedName = name.trim();
    const trimmedBaseUrl = baseUrl.trim();
    const trimmedModel = model.trim();
    if (!trimmedName || !trimmedBaseUrl || !trimmedModel) return;
    if (!isEdit && !token.trim()) return;

    const params = {
      name: trimmedName,
      baseUrl: trimmedBaseUrl,
      model: trimmedModel,
      token: token.trim() || undefined,
      wireApi,
    };

    if (isEdit) {
      updateConnection.mutate({ connectionId: state.connectionId, ...params }, { onSuccess: () => onClose() });
    } else {
      createConnection.mutate(params, { onSuccess: () => onClose() });
    }
  };

  return (
    <Modal title={isEdit ? `Редактировать: ${state.name}` : "Новое подключение к внешней LLM"} onClose={onClose}>
      {isEdit && detail.isPending && <Spinner label="Загрузка подключения…" />}
      {isEdit && detail.isError && <ErrorBanner error={detail.error} onRetry={() => detail.refetch()} />}

      {(!isEdit || prefilled) && (
        <form
          className={styles.form}
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <label>
            Имя
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="my-provider" />
          </label>
          <label>
            Base URL
            <input
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="https://api.example.com/v1"
            />
          </label>
          <label>
            Модель
            <input value={model} onChange={(event) => setModel(event.target.value)} placeholder="my-model" />
          </label>
          <label>
            Токен{isEdit ? " (оставьте пустым, чтобы не менять)" : ""}
            <input
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="sk-…"
              autoComplete="off"
            />
          </label>
          <label>
            Wire API
            <select value={wireApi} onChange={(event) => setWireApi(event.target.value as "chat" | "responses")}>
              <option value="responses">responses</option>
              <option value="chat">chat (устаревший, не поддерживается codex)</option>
            </select>
          </label>

          <Button type="submit" variant="primary" disabled={mutation.isPending}>
            {isEdit ? "Сохранить" : "Создать"}
          </Button>
        </form>
      )}

      {mutation.isError && <ErrorBanner error={mutation.error} onRetry={() => {}} />}
    </Modal>
  );
}
