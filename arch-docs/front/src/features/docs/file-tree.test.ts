import { describe, expect, it } from "vitest";
import { ancestorPaths } from "./file-tree";

describe("ancestorPaths", () => {
  it("возвращает все родительские каталоги для вложенного файла", () => {
    const result = ancestorPaths("architecture/services/gateway.md");
    expect(result).toEqual(new Set(["architecture", "architecture/services"]));
  });

  it("возвращает пустой набор для файла в корне", () => {
    const result = ancestorPaths("README.md");
    expect(result).toEqual(new Set());
  });

  it("не включает сам целевой путь", () => {
    const result = ancestorPaths("a/b/c.md");
    expect(result.has("a/b/c.md")).toBe(false);
  });
});
