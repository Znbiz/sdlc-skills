import { useEffect, useState } from "react";
import { Button } from "../../shared/ui/button";
import { Card } from "../../shared/ui/card";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { Modal } from "../../shared/ui/modal";
import { Spinner } from "../../shared/ui/spinner";
import {
  useCreateLlmProviderConnection,
  useDeleteLlmProviderConnection,
  useLlmProviderConnection,
  useLlmProviderConnections,
  useUpdateLlmProviderConnection,
} from "./hooks";
import styles from "./llm-providers-card.module.css";

type ModalState = { mode: "create" } | { mode: "edit"; connectionId: string; name: string };

export function LlmProvidersCard() {
  const connections = useLlmProviderConnections();
  const deleteConnection = useDeleteLlmProviderConnection();
  const [modalState, setModalState] = useState<ModalState | null>(null);

  return (
    <Card title="Внешние LLM-провайдеры (OpenAI-совместимые)">
      {connections.isPending && <Spinner label="Загрузка подключений…" />}
      {connections.isError && <ErrorBanner error={connections.error} onRetry={() => connections.refetch()} />}

      {connections.data && (
        <ul className={styles.list}>
          {connections.data.length === 0 && <li className={styles.empty}>Пока нет подключённых внешних LLM</li>}
          {connections.data.map((connection) => (
            <li key={connection.connection_id} className={styles.item}>
              <span className={styles.name}>{connection.name}</span>
              <span className={styles.model}>{connection.model}</span>
              <div className={styles.itemActions}>
                <button
                  type="button"
                  className={styles.iconButton}
                  aria-label={`Редактировать ${connection.name}`}
                  onClick={() =>
                    setModalState({ mode: "edit", connectionId: connection.connection_id, name: connection.name })
                  }
                >
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
            </li>
          ))}
        </ul>
      )}

      {deleteConnection.isError && <ErrorBanner error={deleteConnection.error} onRetry={() => {}} />}

      <Button variant="primary" onClick={() => setModalState({ mode: "create" })}>
        Новое подключение
      </Button>

      {modalState && <LlmProviderConnectionModal state={modalState} onClose={() => setModalState(null)} />}
    </Card>
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
  const [prefilled, setPrefilled] = useState(!isEdit);

  useEffect(() => {
    if (isEdit && detail.data && !prefilled) {
      setName(detail.data.name);
      setBaseUrl(detail.data.base_url);
      setModel(detail.data.model);
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

          <Button type="submit" variant="primary" disabled={mutation.isPending}>
            {isEdit ? "Сохранить" : "Создать"}
          </Button>
        </form>
      )}

      {mutation.isError && <ErrorBanner error={mutation.error} onRetry={() => {}} />}
    </Modal>
  );
}
