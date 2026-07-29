import { describe, expect, it } from "vitest";
import { INITIAL_STREAM_STATE, reduceStreamEvent } from "./stream-events";

describe("reduceStreamEvent", () => {
  it("накапливает step_started как читаемую запись", () => {
    const state = reduceStreamEvent(INITIAL_STREAM_STATE, { event_type: "step_started", step_id: "define_scope", repo_name: "acme/repo" });
    expect(state.entries).toHaveLength(1);
    expect(state.entries[0].message).toContain("define_scope");
    expect(state.entries[0].message).toContain("acme/repo");
    expect(state.isTerminal).toBe(false);
  });

  it("помечает workflow_done как терминальное событие", () => {
    const state = reduceStreamEvent(INITIAL_STREAM_STATE, { event_type: "workflow_done" });
    expect(state.isTerminal).toBe(true);
  });

  it("помечает workflow_failed как терминальное событие с сообщением об ошибке", () => {
    const state = reduceStreamEvent(INITIAL_STREAM_STATE, { event_type: "workflow_failed", error_message: "boom" });
    expect(state.isTerminal).toBe(true);
    expect(state.entries[0].message).toContain("boom");
  });

  it("не сбрасывает isTerminal после уже терминального состояния", () => {
    const terminal = reduceStreamEvent(INITIAL_STREAM_STATE, { event_type: "workflow_done" });
    const next = reduceStreamEvent(terminal, { event_type: "cli_output", event_data: "noise after done" });
    expect(next.isTerminal).toBe(true);
  });

  it("обрезает журнал до последних 500 записей", () => {
    let state = INITIAL_STREAM_STATE;
    for (let i = 0; i < 510; i += 1) {
      state = reduceStreamEvent(state, { event_type: "cli_output", event_data: `line-${i}` });
    }
    expect(state.entries).toHaveLength(500);
    expect(state.entries[0].message).toBe("line-10");
  });

  it("использует step_label и обновляет мету текущего шага", () => {
    const state = reduceStreamEvent(INITIAL_STREAM_STATE, {
      event_type: "step_started",
      step_id: "analyze_repositories",
      step_label: "Анализ репозиториев",
      repo_name: "svc-a",
    });
    expect(state.entries[0].message).toBe("Шаг: Анализ репозиториев (svc-a)");
    expect(state.currentStepId).toBe("analyze_repositories");
    expect(state.currentStepLabel).toBe("Анализ репозиториев");
    expect(state.currentRepoName).toBe("svc-a");
  });

  it("не сбрасывает мету текущего шага на не-step_started событиях", () => {
    const afterStep = reduceStreamEvent(INITIAL_STREAM_STATE, {
      event_type: "step_started",
      step_id: "analyze_repositories",
      step_label: "Анализ репозиториев",
      repo_name: "svc-a",
    });
    const afterLlm = reduceStreamEvent(afterStep, { event_type: "llm_message", actor: "llm", text: "hi" });
    expect(afterLlm.currentStepLabel).toBe("Анализ репозиториев");
    expect(afterLlm.currentRepoName).toBe("svc-a");
  });

  it("помечает actor у llm-событий и заполняет detail промптом", () => {
    const state = reduceStreamEvent(INITIAL_STREAM_STATE, {
      event_type: "llm_call_started",
      actor: "llm",
      engine_name: "claude",
      step_label: "Анализ репозиториев",
      repo_name: "svc-a",
      prompt_text: "do the analysis",
    });
    expect(state.entries[0].actor).toBe("llm");
    expect(state.entries[0].message).toContain("claude");
    expect(state.entries[0].detail).toBe("do the analysis");
  });

  it("рендерит llm_tool_call как строку вызова инструмента", () => {
    const state = reduceStreamEvent(INITIAL_STREAM_STATE, {
      event_type: "llm_tool_call",
      actor: "llm",
      tool_name: "Read",
      tool_input: '{"file_path":"a.py"}',
    });
    expect(state.entries[0].message).toBe('🔧 Read({"file_path":"a.py"})');
  });

  it("рендерит llm_call_completed с detail в виде raw_output", () => {
    const state = reduceStreamEvent(INITIAL_STREAM_STATE, {
      event_type: "llm_call_completed",
      actor: "llm",
      raw_output: '{"notes":"ok"}',
    });
    expect(state.entries[0].detail).toBe('{"notes":"ok"}');
  });

  it("рендерит llm_call_failed с причиной ошибки", () => {
    const state = reduceStreamEvent(INITIAL_STREAM_STATE, {
      event_type: "llm_call_failed",
      actor: "llm",
      error_reason: "limit_exhausted",
    });
    expect(state.entries[0].message).toContain("limit_exhausted");
  });

  it("по умолчанию считает actor workflow, если backend его не прислал", () => {
    const state = reduceStreamEvent(INITIAL_STREAM_STATE, { event_type: "artifact_written" });
    expect(state.entries[0].actor).toBe("workflow");
  });

  it("заполняет tokenUsageByModel из llm_call_completed", () => {
    const state = reduceStreamEvent(INITIAL_STREAM_STATE, {
      event_type: "llm_call_completed",
      actor: "llm",
      token_usage_by_model: {
        "claude-sonnet-4-5": { input_tokens: 100, output_tokens: 20 },
      },
    });
    expect(state.tokenUsageByModel).toEqual({
      "claude-sonnet-4-5": { inputTokens: 100, outputTokens: 20 },
    });
  });

  it("заменяет tokenUsageByModel новым кумулятивным снимком, а не суммирует дельты", () => {
    const first = reduceStreamEvent(INITIAL_STREAM_STATE, {
      event_type: "llm_call_completed",
      actor: "llm",
      token_usage_by_model: { "claude-sonnet-4-5": { input_tokens: 100, output_tokens: 20 } },
    });
    const second = reduceStreamEvent(first, {
      event_type: "llm_call_failed",
      actor: "llm",
      token_usage_by_model: {
        "claude-sonnet-4-5": { input_tokens: 150, output_tokens: 30 },
        "gpt-4o-mini": { input_tokens: 10, output_tokens: 2 },
      },
    });
    expect(second.tokenUsageByModel).toEqual({
      "claude-sonnet-4-5": { inputTokens: 150, outputTokens: 30 },
      "gpt-4o-mini": { inputTokens: 10, outputTokens: 2 },
    });
  });

  it("сохраняет предыдущий tokenUsageByModel, если событие его не содержит", () => {
    const withUsage = reduceStreamEvent(INITIAL_STREAM_STATE, {
      event_type: "llm_call_completed",
      actor: "llm",
      token_usage_by_model: { "claude-sonnet-4-5": { input_tokens: 100, output_tokens: 20 } },
    });
    const afterUnrelatedEvent = reduceStreamEvent(withUsage, { event_type: "llm_message", actor: "llm", text: "hi" });
    expect(afterUnrelatedEvent.tokenUsageByModel).toEqual({
      "claude-sonnet-4-5": { inputTokens: 100, outputTokens: 20 },
    });
  });

  it("не падает на некорректном значении token_usage_by_model", () => {
    const state = reduceStreamEvent(INITIAL_STREAM_STATE, {
      event_type: "llm_call_completed",
      actor: "llm",
      token_usage_by_model: "not-an-object",
    });
    expect(state.tokenUsageByModel).toEqual({});
  });
});
