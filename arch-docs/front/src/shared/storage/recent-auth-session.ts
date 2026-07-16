import type { CliEngine } from "../api/models";

function storageKey(cliEngine: CliEngine): string {
  return `arch-docs-front:last-auth-session:${cliEngine}`;
}

export function getLastAuthSessionId(cliEngine: CliEngine): string | null {
  try {
    return window.localStorage.getItem(storageKey(cliEngine));
  } catch {
    return null;
  }
}

export function setLastAuthSessionId(cliEngine: CliEngine, authSessionId: string): void {
  try {
    window.localStorage.setItem(storageKey(cliEngine), authSessionId);
  } catch {
    // localStorage может быть недоступен — сессию просто не удастся восстановить после reload.
  }
}

export function clearLastAuthSessionId(cliEngine: CliEngine): void {
  try {
    window.localStorage.removeItem(storageKey(cliEngine));
  } catch {
    // no-op
  }
}
