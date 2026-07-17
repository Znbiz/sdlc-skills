import { useCallback, useEffect, useState } from "react";
import { cliAuthApi } from "../../shared/api/endpoints";
import { useEventSource } from "../../shared/sse/use-event-source";
import { Button } from "../../shared/ui/button";
import { StatusBadge } from "../../shared/ui/status-badge";
import { toneFromAuthFlowStatus } from "../../shared/status/status-mapping";
import { useAuthSession, useSubmitAuthCode } from "./hooks";
import styles from "./auth-session-panel.module.css";

interface AuthEvent {
  event_type: "instructions" | "auth_success" | "auth_failed" | "error";
  event_data?: string;
  error_message?: string;
}

export function AuthSessionPanel({ authSessionId, onSettled }: { authSessionId: string; onSettled: () => void }) {
  const [logLines, setLogLines] = useState<string[]>([]);
  const [code, setCode] = useState("");
  const session = useAuthSession(authSessionId);
  const submitCode = useSubmitAuthCode();

  const streamUrl = cliAuthApi.authSessionStreamUrl(authSessionId);

  const onMessage = useCallback((event: MessageEvent<string>) => {
    try {
      const parsed = JSON.parse(event.data) as AuthEvent;
      if (parsed.event_type === "instructions" && parsed.event_data) {
        setLogLines((prev) => [...prev, parsed.event_data!]);
      }
    } catch {
      // событие не в ожидаемом формате — игнорируем, snapshot остаётся источником истины
    }
  }, []);

  const connectionState = useEventSource(streamUrl, {
    onMessage,
    onReconnect: () => session.refetch(),
  });

  const authFlowStatus = session.data?.auth_flow_status;
  const isTerminal = authFlowStatus === "success" || authFlowStatus === "failed" || authFlowStatus === "expired";

  useEffect(() => {
    if (isTerminal) onSettled();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isTerminal]);

  return (
    <div className={styles.panel}>
      <div className={styles.statusRow}>
        <StatusBadge tone={toneFromAuthFlowStatus(authFlowStatus ?? "pending")} />
        {connectionState === "reconnecting" && <span className={styles.degraded}>соединение прервано, переподключаемся…</span>}
      </div>
      {(session.data?.verification_uri || session.data?.user_code) && (
        <div className={styles.deviceAuth}>
          {session.data.verification_uri && (
            <p className={styles.instructions}>
              1. Откройте{" "}
              <a href={session.data.verification_uri} target="_blank" rel="noreferrer">
                {session.data.verification_uri}
              </a>{" "}
              и войдите в аккаунт
            </p>
          )}
          {session.data.user_code && (
            <p className={styles.instructions}>
              2. Введите на этой странице код: <code className={styles.userCode}>{session.data.user_code}</code>
            </p>
          )}
        </div>
      )}
      {!session.data?.verification_uri && session.data?.instructions && (
        <p className={styles.instructions}>{session.data.instructions}</p>
      )}
      {logLines.length > 0 && (
        <pre className={styles.log} aria-label="Журнал авторизации">
          {logLines.join("\n")}
        </pre>
      )}
      {!isTerminal && (
        <form
          className={styles.codeForm}
          onSubmit={(event) => {
            event.preventDefault();
            if (!code.trim()) return;
            submitCode.mutate(
              { authSessionId, code: code.trim() },
              {
                onSuccess: () => {
                  setCode("");
                  session.refetch();
                },
              },
            );
          }}
        >
          <label htmlFor="auth-code">Код подтверждения (если backend его запросил)</label>
          <div className={styles.codeRow}>
            <input id="auth-code" value={code} onChange={(event) => setCode(event.target.value)} placeholder="Введите код" />
            <Button type="submit" variant="secondary" disabled={submitCode.isPending}>
              Отправить
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}
