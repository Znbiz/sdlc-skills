import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "../../test/msw-server";
import { ApiError } from "../errors/api-error";
import { cliAuthApi, docsApi, gitCredentialsApi } from "./endpoints";

describe("cliAuthApi.getStatus", () => {
  it("парсит успешный ответ backend в типизированную модель", async () => {
    server.use(
      http.get("/api/rest/cli-auth/", () =>
        HttpResponse.json({
          codex: { authenticated: true, auth_status: "ok", auth_file_exists: true },
          claude: { authenticated: false, auth_status: "not_initialized", auth_file_exists: false },
        }),
      ),
    );

    const status = await cliAuthApi.getStatus();
    expect(status.codex.authenticated).toBe(true);
    expect(status.claude.auth_status).toBe("not_initialized");
  });
});

describe("маппинг ошибок backend", () => {
  it("превращает 404 с detail-строкой в ApiError с kind=not_found", async () => {
    server.use(
      http.post("/api/rest/git-credentials/check-access/", () =>
        HttpResponse.json({ detail: "repository not found" }, { status: 404 }),
      ),
    );

    await expect(gitCredentialsApi.checkAccess("https://example.com/repo.git")).rejects.toMatchObject({
      kind: "not_found",
      message: "repository not found",
    });
  });

  it("извлекает typed reason_code из detail-объекта вместо парсинга свободного текста", async () => {
    server.use(
      http.get("/api/rest/responses/resp-1/docs/file/", () =>
        HttpResponse.json({ detail: { reason_code: "path_forbidden", message: "запрещённый путь" } }, { status: 403 }),
      ),
    );

    try {
      await docsApi.getFile("resp-1", "../../etc/passwd");
      expect.unreachable("ожидалась ошибка");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      const apiError = error as ApiError;
      expect(apiError.kind).toBe("forbidden");
      expect(apiError.reasonCode).toBe("path_forbidden");
      expect(apiError.message).toBe("запрещённый путь");
    }
  });

  it("оборачивает сетевые сбои в transport-ошибку", async () => {
    server.use(http.get("/api/rest/cli-auth/", () => HttpResponse.error()));

    await expect(cliAuthApi.getStatus()).rejects.toMatchObject({ kind: "transport" });
  });
});
