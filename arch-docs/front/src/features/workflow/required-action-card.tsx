import { useState } from "react";
import type { RequiredActionResponse } from "../../shared/api/models";
import { Button } from "../../shared/ui/button";
import { Card } from "../../shared/ui/card";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { useSubmitResponseAction } from "./hooks";
import styles from "./required-action-card.module.css";

const TEMPORAL_WINDOW_OPTIONS: { value: string; label: string }[] = [
  { value: "continue_to_next_window", label: "Продолжить со следующим окном" },
  { value: "finish_temporal_analysis", label: "Завершить исторический анализ" },
];

export function RequiredActionCard({
  responseId,
  conversationId,
  action,
}: {
  responseId: string;
  conversationId: string;
  action: RequiredActionResponse;
}) {
  const submitAction = useSubmitResponseAction(conversationId);
  const [text, setText] = useState("");

  const renderForm = () => {
    switch (action.action_type) {
      case "user_question":
        return (
          <form
            className={styles.form}
            onSubmit={(event) => {
              event.preventDefault();
              if (!text.trim()) return;
              submitAction.mutate({ responseId, actionType: "answer_question", questionId: action.question_id, answer: text.trim() });
            }}
          >
            <p className={styles.question}>{String(action.payload.question ?? "")}</p>
            <textarea value={text} onChange={(event) => setText(event.target.value)} rows={3} />
            <Button type="submit" variant="primary" disabled={submitAction.isPending}>
              Ответить
            </Button>
          </form>
        );
      case "user_input":
        return (
          <form
            className={styles.form}
            onSubmit={(event) => {
              event.preventDefault();
              if (!text.trim()) return;
              submitAction.mutate({
                responseId,
                actionType: "resume",
                field: String(action.payload.field ?? ""),
                value: text.trim(),
              });
            }}
          >
            <p className={styles.question}>{String(action.payload.question ?? "")}</p>
            <input value={text} onChange={(event) => setText(event.target.value)} />
            <Button type="submit" variant="primary" disabled={submitAction.isPending}>
              Продолжить
            </Button>
          </form>
        );
      case "temporal_window_confirmation":
        return (
          <div className={styles.form}>
            <p className={styles.question}>
              Следующее окно: {String(action.payload.next_snapshot_at ?? "")}
            </p>
            <div className={styles.actions}>
              {TEMPORAL_WINDOW_OPTIONS.map((option) => (
                <Button
                  key={option.value}
                  variant="primary"
                  disabled={submitAction.isPending}
                  onClick={() => submitAction.mutate({ responseId, actionType: "confirm_temporal_window", value: option.value })}
                >
                  {option.label}
                </Button>
              ))}
            </div>
          </div>
        );
      default:
        return (
          <p className={styles.unsupported}>
            Backend запросил действие типа «{action.action_type}», для которого пока нет специализированной формы.
          </p>
        );
    }
  };

  return (
    <Card title="Требуется действие">
      {renderForm()}
      {submitAction.isError && <ErrorBanner error={submitAction.error} onRetry={() => {}} />}
    </Card>
  );
}
