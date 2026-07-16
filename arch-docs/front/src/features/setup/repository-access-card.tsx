import { useState } from "react";
import { Button } from "../../shared/ui/button";
import { Card } from "../../shared/ui/card";
import { StatusBadge } from "../../shared/ui/status-badge";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { toneFromAccessStatus } from "../../shared/status/status-mapping";
import { useCheckGitAccess } from "./hooks";
import styles from "./repository-access-card.module.css";

export function RepositoryAccessCard() {
  const [repositoryUrl, setRepositoryUrl] = useState("");
  const checkAccess = useCheckGitAccess();

  return (
    <Card title="Проверка доступа к репозиторию">
      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          if (!repositoryUrl.trim()) return;
          checkAccess.mutate(repositoryUrl.trim());
        }}
      >
        <input
          value={repositoryUrl}
          onChange={(event) => setRepositoryUrl(event.target.value)}
          placeholder="https://github.com/org/repo.git"
        />
        <Button type="submit" variant="primary" disabled={checkAccess.isPending}>
          Проверить доступ
        </Button>
      </form>

      {checkAccess.isError && <ErrorBanner error={checkAccess.error} onRetry={() => checkAccess.mutate(repositoryUrl.trim())} />}

      {checkAccess.data && (
        <div className={styles.result}>
          <StatusBadge tone={toneFromAccessStatus(checkAccess.data.accessible)} label={checkAccess.data.accessible ? "Доступ есть" : "Доступа нет"} />
          <p className={styles.message}>{checkAccess.data.message}</p>
        </div>
      )}
    </Card>
  );
}
