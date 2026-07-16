import { useState } from "react";
import { Button } from "../../shared/ui/button";
import { Card } from "../../shared/ui/card";
import { StatusBadge } from "../../shared/ui/status-badge";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { Spinner } from "../../shared/ui/spinner";
import { useDeleteGitToken, useGitCredentialsStatus, useSetGitToken } from "./hooks";
import styles from "./git-token-card.module.css";

export function GitTokenCard() {
  const status = useGitCredentialsStatus();
  const setToken = useSetGitToken();
  const deleteToken = useDeleteGitToken();

  const [host, setHost] = useState("github.com");
  const [token, setToken2] = useState("");
  const [username, setUsername] = useState("");

  if (status.isPending) return <Card title="Personal Access Token"><Spinner /></Card>;
  if (status.isError) return <Card title="Personal Access Token"><ErrorBanner error={status.error} onRetry={() => status.refetch()} /></Card>;

  return (
    <Card title="Personal Access Token">
      <StatusBadge tone={status.data.configured ? "completed" : "idle"} label={status.data.configured ? "Токен сохранён" : "Токен не задан"} />

      {status.data.configured_hosts.length > 0 && (
        <ul className={styles.hostList}>
          {status.data.configured_hosts.map((configuredHost) => (
            <li key={configuredHost}>
              <span>{configuredHost}</span>
              <Button
                variant="danger"
                disabled={deleteToken.isPending}
                onClick={() => deleteToken.mutate(configuredHost)}
              >
                Удалить
              </Button>
            </li>
          ))}
        </ul>
      )}

      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          if (!host.trim() || !token.trim()) return;
          setToken.mutate(
            { host: host.trim(), token: token.trim(), username: username.trim() || undefined },
            { onSuccess: () => setToken2("") },
          );
        }}
      >
        <label>
          Хост
          <input value={host} onChange={(event) => setHost(event.target.value)} placeholder="github.com" />
        </label>
        <label>
          Токен
          <input type="password" value={token} onChange={(event) => setToken2(event.target.value)} placeholder="ghp_…" autoComplete="off" />
        </label>
        <label>
          Имя пользователя (опционально)
          <input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="oauth2" />
        </label>
        <Button type="submit" variant="primary" disabled={setToken.isPending}>
          Сохранить токен
        </Button>
      </form>

      {setToken.isError && <ErrorBanner error={setToken.error} onRetry={() => {}} />}
      {deleteToken.isError && <ErrorBanner error={deleteToken.error} onRetry={() => {}} />}
    </Card>
  );
}
