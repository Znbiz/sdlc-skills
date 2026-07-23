import type { RequiredActionResponse } from "../../shared/api/models";
import { Card } from "../../shared/ui/card";
import styles from "./queued-questions-card.module.css";

export function QueuedQuestionsCard({ questions }: { questions: RequiredActionResponse[] }) {
  if (questions.length === 0) return null;

  return (
    <Card title={`Открытые вопросы в очереди (${questions.length})`}>
      <p className={styles.hint}>
        Уже собраны во время анализа репозиториев. Форма для ответа появится по одному, на шаге «Интервью» —
        после того как анализ всех репозиториев завершится (если сейчас workflow на паузе, сначала нажмите
        «Продолжить»).
      </p>
      <ul className={styles.list}>
        {questions.map((question) => (
          <li key={question.question_id}>{String(question.payload.question_text ?? "")}</li>
        ))}
      </ul>
    </Card>
  );
}
