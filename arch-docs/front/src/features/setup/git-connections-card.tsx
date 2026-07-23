import { useEffect, useState } from "react";
import { Button } from "../../shared/ui/button";
import { Card } from "../../shared/ui/card";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { Modal } from "../../shared/ui/modal";
import { Spinner } from "../../shared/ui/spinner";
import type { GitConnectionType } from "../../shared/api/models";
import {
  useCreateGitConnection,
  useDeleteGitConnection,
  useGitConnection,
  useGitConnections,
  useGitSshPublicKey,
  useUpdateGitConnection,
} from "./hooks";
import styles from "./git-connections-card.module.css";

type ModalState = { mode: "create" } | { mode: "edit"; connectionId: string; host: string };

const CONNECTION_TYPE_LABELS: Record<GitConnectionType, string> = {
  token: "Token",
  ssh: "SSH",
};

function normalizeHost(rawHost: string): string {
  return rawHost
    .trim()
    .replace(/^[a-z][a-z0-9+.-]*:\/\//i, "")
    .split("/")[0]
    .trim();
}

export function GitConnectionsCard() {
  const connections = useGitConnections();
  const deleteConnection = useDeleteGitConnection();
  const [modalState, setModalState] = useState<ModalState | null>(null);

  return (
    <Card title="Git-подключения">
      {connections.isPending && <Spinner label="Загрузка подключений…" />}
      {connections.isError && <ErrorBanner error={connections.error} onRetry={() => connections.refetch()} />}

      {connections.data && (
        <ul className={styles.list}>
          {connections.data.length === 0 && <li className={styles.empty}>Пока нет подключённых Git-систем</li>}
          {connections.data.map((connection) => (
            <li key={connection.connection_id} className={styles.item}>
              <span className={styles.host}>{connection.host}</span>
              <span className={`${styles.typeBadge} ${styles[connection.connection_type]}`}>
                {CONNECTION_TYPE_LABELS[connection.connection_type]}
              </span>
              <div className={styles.itemActions}>
                <button
                  type="button"
                  className={styles.iconButton}
                  aria-label={`Редактировать ${connection.host}`}
                  onClick={() =>
                    setModalState({ mode: "edit", connectionId: connection.connection_id, host: connection.host })
                  }
                >
                  ✎
                </button>
                <button
                  type="button"
                  className={styles.iconButton}
                  aria-label={`Удалить ${connection.host}`}
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
        Новая интеграция
      </Button>

      {modalState && <GitConnectionModal state={modalState} onClose={() => setModalState(null)} />}
    </Card>
  );
}

function GitConnectionModal({ state, onClose }: { state: ModalState; onClose: () => void }) {
  const isEdit = state.mode === "edit";
  const existingConnectionId = isEdit ? state.connectionId : null;
  const detail = useGitConnection(existingConnectionId);
  const createConnection = useCreateGitConnection();
  const updateConnection = useUpdateGitConnection();
  const publicKey = useGitSshPublicKey();

  const [host, setHost] = useState(isEdit ? state.host : "");
  const [connectionType, setConnectionType] = useState<GitConnectionType>("token");
  const [token, setToken] = useState("");
  const [username, setUsername] = useState("");
  const [prefilled, setPrefilled] = useState(!isEdit);

  useEffect(() => {
    if (isEdit && detail.data && !prefilled) {
      setHost(detail.data.host);
      setConnectionType(detail.data.connection_type);
      setToken(detail.data.token ?? "");
      setUsername(detail.data.username ?? "");
      setPrefilled(true);
    }
  }, [isEdit, detail.data, prefilled]);

  const mutation = isEdit ? updateConnection : createConnection;

  const submit = () => {
    const normalizedHost = normalizeHost(host);
    if (!normalizedHost) return;
    if (connectionType === "token" && !token.trim()) return;

    const params = {
      host: normalizedHost,
      connectionType,
      token: connectionType === "token" ? token.trim() : undefined,
      username: connectionType === "token" ? username.trim() || undefined : undefined,
    };

    if (isEdit) {
      updateConnection.mutate({ connectionId: state.connectionId, ...params }, { onSuccess: () => onClose() });
    } else {
      createConnection.mutate(params, { onSuccess: () => onClose() });
    }
  };

  return (
    <Modal title={isEdit ? `Редактировать: ${state.host}` : "Новая git-система"} onClose={onClose}>
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
            Хост
            <input value={host} onChange={(event) => setHost(event.target.value)} placeholder="github.com" />
          </label>

          <div className={styles.methodRow} role="radiogroup" aria-label="Способ подключения">
            <label className={styles.methodOption}>
              <input
                type="radio"
                name="connection-type"
                value="token"
                checked={connectionType === "token"}
                onChange={() => setConnectionType("token")}
              />
              Token
            </label>
            <label className={styles.methodOption}>
              <input
                type="radio"
                name="connection-type"
                value="ssh"
                checked={connectionType === "ssh"}
                onChange={() => setConnectionType("ssh")}
              />
              SSH
            </label>
          </div>

          {connectionType === "token" ? (
            <>
              <label>
                Токен
                <input
                  type="password"
                  value={token}
                  onChange={(event) => setToken(event.target.value)}
                  placeholder="ghp_…"
                  autoComplete="off"
                />
              </label>
              <label>
                Имя пользователя (опционально)
                <input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="oauth2" />
              </label>
            </>
          ) : (
            <div className={styles.keyBlock}>
              <p className={styles.hint}>
                Один SSH-ключ на весь сервис — добавьте его как SSH-ключ (или Deploy Key) у Git-провайдера.
              </p>
              {publicKey.isPending && <Spinner label="Загрузка ключа…" />}
              {publicKey.isError && <ErrorBanner error={publicKey.error} onRetry={() => publicKey.refetch()} />}
              {publicKey.data && <textarea className={styles.keyText} readOnly value={publicKey.data.public_key} rows={3} />}
            </div>
          )}

          <Button type="submit" variant="primary" disabled={mutation.isPending}>
            {isEdit ? "Сохранить" : "Создать"}
          </Button>
        </form>
      )}

      {mutation.isError && <ErrorBanner error={mutation.error} onRetry={() => {}} />}
    </Modal>
  );
}
