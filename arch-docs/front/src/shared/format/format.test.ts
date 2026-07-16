import { describe, expect, it } from "vitest";
import { formatFileSize } from "./format";

describe("formatFileSize", () => {
  it("оставляет байты как есть ниже 1024", () => {
    expect(formatFileSize(512)).toBe("512 Б");
  });

  it("переходит в КБ на границе 1024", () => {
    expect(formatFileSize(1024)).toBe("1.0 КБ");
  });

  it("переходит в МБ", () => {
    expect(formatFileSize(1024 * 1024 * 2.5)).toBe("2.5 МБ");
  });
});
