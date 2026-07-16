export interface StreamLogEntry {
  eventType: string;
  message: string;
}

export interface StreamReducerState {
  entries: StreamLogEntry[];
  isTerminal: boolean;
}

export const INITIAL_STREAM_STATE: StreamReducerState = { entries: [], isTerminal: false };

const MAX_ENTRIES = 500;

function describeEvent(raw: Record<string, unknown>): StreamLogEntry {
  const eventType = String(raw.event_type ?? "unknown");
  switch (eventType) {
    case "step_started":
      return { eventType, message: `Шаг: ${raw.step_id ?? ""}${raw.repo_name ? ` (${raw.repo_name})` : ""}` };
    case "cli_output":
    case "output":
      return { eventType, message: String(raw.event_data ?? "") };
    case "progress":
      return { eventType, message: String(raw.event_data ?? "") };
    case "interrupted":
      return { eventType, message: `Требуется действие: ${raw.interrupt_type ?? raw.question ?? ""}` };
    case "workflow_done":
    case "done":
      return { eventType, message: "Workflow завершён" };
    case "workflow_failed":
      return { eventType, message: `Ошибка: ${raw.error_message ?? "unknown error"}` };
    case "workflow_cancelled":
      return { eventType, message: "Workflow отменён" };
    case "error":
      return { eventType, message: String(raw.error_message ?? "Ошибка потока") };
    default:
      return { eventType, message: JSON.stringify(raw) };
  }
}

const TERMINAL_EVENT_TYPES = new Set(["workflow_done", "done", "workflow_failed", "workflow_cancelled", "error"]);

export function reduceStreamEvent(state: StreamReducerState, rawPayload: Record<string, unknown>): StreamReducerState {
  const entry = describeEvent(rawPayload);
  const entries = [...state.entries, entry].slice(-MAX_ENTRIES);
  const isTerminal = state.isTerminal || TERMINAL_EVENT_TYPES.has(entry.eventType);
  return { entries, isTerminal };
}
