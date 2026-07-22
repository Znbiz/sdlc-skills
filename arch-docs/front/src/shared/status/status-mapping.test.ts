import { describe, expect, it } from "vitest";
import {
  responseStatusLabel,
  toneFromAccessStatus,
  toneFromAuthFlowStatus,
  toneFromAuthStatus,
  toneFromResponseStatus,
} from "./status-mapping";

describe("toneFromAuthStatus", () => {
  it("маркирует авторизованный CLI как completed", () => {
    expect(toneFromAuthStatus(true, "ok")).toBe("completed");
  });

  it("маркирует не инициализированный CLI как idle", () => {
    expect(toneFromAuthStatus(false, "not_initialized")).toBe("idle");
  });

  it("маркирует истёкшую авторизацию как failed", () => {
    expect(toneFromAuthStatus(false, "auth_expired")).toBe("failed");
  });
});

describe("toneFromAccessStatus", () => {
  it("возвращает completed при доступе", () => {
    expect(toneFromAccessStatus(true)).toBe("completed");
  });

  it("возвращает failed при отсутствии доступа", () => {
    expect(toneFromAccessStatus(false)).toBe("failed");
  });
});

describe("toneFromAuthFlowStatus", () => {
  it.each([
    ["pending", "in_progress"],
    ["success", "completed"],
    ["failed", "failed"],
    ["expired", "failed"],
    ["weird", "unknown"],
  ] as const)("%s -> %s", (status, expected) => {
    expect(toneFromAuthFlowStatus(status)).toBe(expected);
  });
});

describe("toneFromResponseStatus", () => {
  it("interrupted с required_actions даёт needs_action", () => {
    expect(toneFromResponseStatus("interrupted", true)).toBe("needs_action");
  });

  it("interrupted без required_actions всё равно needs_action по статусу", () => {
    expect(toneFromResponseStatus("interrupted", false)).toBe("needs_action");
  });

  it("running -> in_progress", () => {
    expect(toneFromResponseStatus("running", false)).toBe("in_progress");
  });

  it("success -> completed", () => {
    expect(toneFromResponseStatus("success", false)).toBe("completed");
  });

  it.each(["failed", "cancelled"] as const)("%s -> failed", (status) => {
    expect(toneFromResponseStatus(status, false)).toBe("failed");
  });

  it("paused -> needs_action", () => {
    expect(toneFromResponseStatus("paused", false)).toBe("needs_action");
  });
});

describe("responseStatusLabel", () => {
  it("возвращает читаемую метку для известных статусов", () => {
    expect(responseStatusLabel("success")).toBe("Завершено успешно");
  });

  it("возвращает читаемую метку для paused", () => {
    expect(responseStatusLabel("paused")).toBe("На паузе");
  });

  it("возвращает исходную строку для неизвестного статуса", () => {
    expect(responseStatusLabel("mystery")).toBe("mystery");
  });
});
