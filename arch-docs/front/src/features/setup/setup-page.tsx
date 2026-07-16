import { ErrorBanner } from "../../shared/ui/error-banner";
import { Spinner } from "../../shared/ui/spinner";
import { AuthEngineCard } from "./auth-engine-card";
import { GitTokenCard } from "./git-token-card";
import { RepositoryAccessCard } from "./repository-access-card";
import { useCliAuthStatus } from "./hooks";
import styles from "./setup-page.module.css";

export function SetupPage() {
  const cliAuthStatus = useCliAuthStatus();

  return (
    <div className={styles.page}>
      <h1>Setup</h1>
      <p className={styles.lead}>Подготовьте среду перед запуском init_arch: авторизация CLI-агентов и доступ к Git.</p>

      <div className={styles.grid}>
        {cliAuthStatus.isPending && <Spinner label="Загрузка статуса авторизации…" />}
        {cliAuthStatus.isError && <ErrorBanner error={cliAuthStatus.error} onRetry={() => cliAuthStatus.refetch()} />}
        {cliAuthStatus.data && (
          <>
            <AuthEngineCard cliEngine="codex" authInfo={cliAuthStatus.data.codex} />
            <AuthEngineCard cliEngine="claude" authInfo={cliAuthStatus.data.claude} />
          </>
        )}
        <GitTokenCard />
        <RepositoryAccessCard />
      </div>
    </div>
  );
}
