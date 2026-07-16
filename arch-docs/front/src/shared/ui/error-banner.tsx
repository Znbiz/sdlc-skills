import { ApiError } from "../errors/api-error";
import { Button } from "./button";
import styles from "./error-banner.module.css";

export function ErrorBanner({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof ApiError ? error.message : "Произошла непредвиденная ошибка.";
  const kindLabel = error instanceof ApiError ? errorKindLabel(error.kind) : null;

  return (
    <div className={styles.banner} role="alert">
      <div>
        {kindLabel && <span className={styles.kind}>{kindLabel}</span>}
        <p className={styles.message}>{message}</p>
      </div>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Повторить
        </Button>
      )}
    </div>
  );
}

function errorKindLabel(kind: ApiError["kind"]): string {
  switch (kind) {
    case "transport":
      return "Нет связи с backend";
    case "validation":
      return "Ошибка валидации";
    case "not_found":
      return "Не найдено";
    case "forbidden":
      return "Доступ запрещён";
    case "conflict":
      return "Конфликт состояния";
    case "server":
      return "Ошибка сервера";
    default:
      return "Ошибка";
  }
}
