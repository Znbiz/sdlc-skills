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
});
