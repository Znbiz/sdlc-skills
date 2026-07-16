import type { StatusTone } from "../ui/status-badge";

export function toneFromAuthStatus(authenticated: boolean, authStatus: string): StatusTone {
  if (authenticated) return "completed";
  if (authStatus === "not_initialized") return "idle";
  if (authStatus === "auth_expired") return "failed";
  return "unknown";
}

export function toneFromAccessStatus(accessible: boolean): StatusTone {
  return accessible ? "completed" : "failed";
}

export function toneFromAuthFlowStatus(authFlowStatus: string): StatusTone {
  switch (authFlowStatus) {
    case "success":
      return "completed";
    case "failed":
    case "expired":
      return "failed";
    case "pending":
      return "in_progress";
    default:
      return "unknown";
  }
}

export function toneFromResponseStatus(responseStatus: string, hasRequiredActions: boolean): StatusTone {
  if (hasRequiredActions && responseStatus === "interrupted") return "needs_action";
  switch (responseStatus) {
    case "success":
      return "completed";
    case "failed":
    case "cancelled":
      return "failed";
    case "interrupted":
      return "needs_action";
    case "running":
      return "in_progress";
    default:
      return "unknown";
  }
}

export function responseStatusLabel(responseStatus: string): string {
  switch (responseStatus) {
    case "running":
      return "Выполняется";
    case "interrupted":
      return "Требует действия";
    case "success":
      return "Завершено успешно";
    case "failed":
      return "Ошибка выполнения";
    case "cancelled":
      return "Отменено";
    default:
      return responseStatus;
  }
}
