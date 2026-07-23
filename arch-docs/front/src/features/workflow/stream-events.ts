export type StreamActor = "workflow" | "llm" | "user";

export interface StreamLogEntry {
  eventType: string;
  actor: StreamActor;
  message: string;
  detail?: string;
  // Backend SSE payloads carry no timestamp (see reduceStreamEvent) - this is receipt time, not
  // server emit time, but for a live-tailing stream the two are close enough to treat as one.
  receivedAt: number;
}

export interface StreamReducerState {
  entries: StreamLogEntry[];
  isTerminal: boolean;
  currentStepId: string;
  currentStepLabel: string;
  currentRepoName: string;
}

export const INITIAL_STREAM_STATE: StreamReducerState = {
  entries: [],
  isTerminal: false,
  currentStepId: "",
  currentStepLabel: "",
  currentRepoName: "",
};

const MAX_ENTRIES = 500;

function resolveActor(raw: Record<string, unknown>): StreamActor {
  const actor = raw.actor;
  if (actor === "llm" || actor === "user" || actor === "workflow") return actor;
  return "workflow";
}

function describeEvent(raw: Record<string, unknown>): Omit<StreamLogEntry, "receivedAt"> {
  const eventType = String(raw.event_type ?? "unknown");
  const actor = resolveActor(raw);
  switch (eventType) {
    case "step_started": {
      const label = raw.step_label ? String(raw.step_label) : String(raw.step_id ?? "");
      return {
        eventType,
        actor,
        message: `Шаг: ${label}${raw.repo_name ? ` (${raw.repo_name})` : ""}`,
      };
    }
    case "cli_output":
    case "output":
      return { eventType, actor, message: String(raw.event_data ?? "") };
    case "progress":
      return { eventType, actor, message: String(raw.event_data ?? "") };
    case "llm_call_started":
      return {
        eventType,
        actor,
        message: `LLM запущен (${raw.engine_name ?? "?"}, ${raw.step_label ?? raw.step_id ?? ""}${raw.repo_name ? `, ${raw.repo_name}` : ""})`,
        detail: raw.prompt_text ? String(raw.prompt_text) : undefined,
      };
    case "llm_tool_call":
      return {
        eventType,
        actor,
        message: `🔧 ${raw.tool_name ?? "tool"}(${raw.tool_input ?? ""})`,
      };
    case "llm_message":
      return { eventType, actor, message: String(raw.text ?? "") };
    case "llm_call_completed":
      return {
        eventType,
        actor,
        message: "LLM завершил вызов",
        detail: raw.raw_output ? String(raw.raw_output) : undefined,
      };
    case "llm_call_failed":
      return {
        eventType,
        actor,
        message: `LLM вызов упал: ${raw.error_reason ?? raw.error ?? "unknown error"}`,
      };
    case "interrupted":
      return { eventType, actor, message: `Требуется действие: ${raw.interrupt_type ?? raw.question ?? ""}` };
    case "workflow_done":
    case "done":
      return { eventType, actor, message: "Workflow завершён" };
    case "workflow_failed":
      return { eventType, actor, message: `Ошибка: ${raw.error_message ?? "unknown error"}` };
    case "workflow_cancelled":
      return { eventType, actor, message: "Workflow отменён" };
    case "error":
      return { eventType, actor, message: String(raw.error_message ?? "Ошибка потока") };
    default:
      return { eventType, actor, message: JSON.stringify(raw) };
  }
}

const TERMINAL_EVENT_TYPES = new Set(["workflow_done", "done", "workflow_failed", "workflow_cancelled", "error"]);

export function reduceStreamEvent(state: StreamReducerState, rawPayload: Record<string, unknown>): StreamReducerState {
  const entry = { ...describeEvent(rawPayload), receivedAt: Date.now() };
  const entries = [...state.entries, entry].slice(-MAX_ENTRIES);
  const isTerminal = state.isTerminal || TERMINAL_EVENT_TYPES.has(entry.eventType);

  const isStepStarted = entry.eventType === "step_started";
  return {
    entries,
    isTerminal,
    currentStepId: isStepStarted ? String(rawPayload.step_id ?? "") : state.currentStepId,
    currentStepLabel: isStepStarted
      ? String(rawPayload.step_label ?? rawPayload.step_id ?? "")
      : state.currentStepLabel,
    currentRepoName: isStepStarted ? String(rawPayload.repo_name ?? "") : state.currentRepoName,
  };
}
