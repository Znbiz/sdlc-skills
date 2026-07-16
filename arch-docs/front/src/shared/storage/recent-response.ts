const STORAGE_KEY = "arch-docs-front:last-response-id";

export function getLastResponseId(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setLastResponseId(responseId: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, responseId);
  } catch {
    // localStorage может быть недоступен — просто не восстановим значение по умолчанию.
  }
}
