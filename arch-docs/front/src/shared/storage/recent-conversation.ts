const STORAGE_KEY = "arch-docs-front:last-conversation-id";

export function getLastConversationId(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setLastConversationId(conversationId: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, conversationId);
  } catch {
    // localStorage может быть недоступен (приватный режим) — это не критично для read-model.
  }
}
