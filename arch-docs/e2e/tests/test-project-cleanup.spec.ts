import { expect, test } from "@playwright/test";
import {
  buildTestProjectName,
  purgeTestProjects,
  TEST_PROJECT_PREFIX,
} from "../helpers/test-projects";

test.describe("e2e test projects", () => {
  test("buildTestProjectName prefixes names with test-", async () => {
    expect(buildTestProjectName("Guard Check")).toBe("test-guard-check");
    expect(buildTestProjectName("Docs Picker Project 123")).toBe("test-docs-picker-project-123");
    expect(buildTestProjectName("  Mixed_CASE Value  ")).toBe("test-mixed-case-value");
    expect(TEST_PROJECT_PREFIX).toBe("test-");
  });

  test("purgeTestProjects removes only prefixed conversations", async () => {
    const deletedPaths: string[] = [];
    const request = {
      async get() {
        return {
          ok: () => true,
          status: () => 200,
          async json() {
            return [
              { conversation_id: "conv-keep", product_name: "manual-keep" },
              { conversation_id: "conv-drop-1", product_name: buildTestProjectName("cleanup one") },
              { conversation_id: "conv-drop-2", product_name: buildTestProjectName("cleanup two") },
              { conversation_id: "conv-empty", product_name: null },
            ];
          },
        };
      },
      async delete(path: string) {
        deletedPaths.push(path);
        return {
          status: () => 204,
        };
      },
    };

    await purgeTestProjects(request);

    expect(deletedPaths).toEqual([
      "/api/rest/conversations/conv-drop-1/",
      "/api/rest/conversations/conv-drop-2/",
    ]);
  });
});
