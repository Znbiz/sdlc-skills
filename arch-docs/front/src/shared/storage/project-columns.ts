const STORAGE_KEY = "arch-docs-front:project-columns-widths";

// Ширины левой и правой колонки (в px) на странице проекта - средняя колонка всегда занимает
// оставшееся место. Осознанно общие для всех проектов (не per-conversation), чтобы пользователь
// один раз настроил комфортный layout и он не сбрасывался при переходе между проектами.
export type ProjectColumnWidths = [left: number, right: number];

export function getProjectColumnWidths(): ProjectColumnWidths | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.length === 2 && parsed.every((value) => typeof value === "number" && value > 0)) {
      return parsed as ProjectColumnWidths;
    }
    return null;
  } catch {
    return null;
  }
}

export function setProjectColumnWidths(widths: ProjectColumnWidths): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(widths));
  } catch {
    // localStorage может быть недоступен (приватный режим) — просто не запомним ширины.
  }
}
