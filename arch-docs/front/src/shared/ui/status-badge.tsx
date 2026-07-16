import styles from "./status-badge.module.css";

export type StatusTone = "idle" | "in_progress" | "needs_action" | "failed" | "completed" | "unknown";

const TONE_LABELS: Record<StatusTone, string> = {
  idle: "Ожидание",
  in_progress: "В процессе",
  needs_action: "Нужно действие",
  failed: "Ошибка",
  completed: "Завершено",
  unknown: "Неизвестно",
};

export function StatusBadge({ tone, label }: { tone: StatusTone; label?: string }) {
  return (
    <span className={`${styles.badge} ${styles[tone]}`} role="status">
      {label ?? TONE_LABELS[tone]}
    </span>
  );
}
