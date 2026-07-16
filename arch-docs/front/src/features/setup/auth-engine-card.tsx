import { useState } from "react";
import type { CliEngine, CliEngineAuthInfo } from "../../shared/api/models";
import { Button } from "../../shared/ui/button";
import { Card } from "../../shared/ui/card";
import { StatusBadge } from "../../shared/ui/status-badge";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { toneFromAuthStatus } from "../../shared/status/status-mapping";
import { clearLastAuthSessionId, getLastAuthSessionId, setLastAuthSessionId } from "../../shared/storage/recent-auth-session";
import { useInitAuth } from "./hooks";
import { AuthSessionPanel } from "./auth-session-panel";

const ENGINE_TITLES: Record<CliEngine, string> = {
  codex: "Codex",
  claude: "Claude",
};

export function AuthEngineCard({ cliEngine, authInfo }: { cliEngine: CliEngine; authInfo: CliEngineAuthInfo }) {
  const [authSessionId, setAuthSessionId] = useState<string | null>(() => getLastAuthSessionId(cliEngine));
  const initAuth = useInitAuth();

  return (
    <Card
      title={ENGINE_TITLES[cliEngine]}
      actions={
        !authInfo.authenticated && !authSessionId ? (
          <Button
            variant="primary"
            disabled={initAuth.isPending}
            onClick={() =>
              initAuth.mutate(cliEngine, {
                onSuccess: (response) => {
                  setLastAuthSessionId(cliEngine, response.auth_session_id);
                  setAuthSessionId(response.auth_session_id);
                },
              })
            }
          >
            Запустить авторизацию
          </Button>
        ) : undefined
      }
    >
      <StatusBadge tone={toneFromAuthStatus(authInfo.authenticated, authInfo.auth_status)} />
      {initAuth.isError && <ErrorBanner error={initAuth.error} onRetry={() => initAuth.mutate(cliEngine)} />}
      {authSessionId && (
        <AuthSessionPanel
          authSessionId={authSessionId}
          onSettled={() => {
            clearLastAuthSessionId(cliEngine);
          }}
        />
      )}
    </Card>
  );
}
