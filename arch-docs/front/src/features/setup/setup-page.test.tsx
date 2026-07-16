import { HttpResponse, http } from "msw";
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { server } from "../../test/msw-server";
import { renderWithProviders } from "../../test/render";
import { SetupPage } from "./setup-page";

describe("SetupPage", () => {
  it("показывает статус авторизации обоих CLI-агентов и readiness Git", async () => {
    server.use(
      http.get("/api/rest/cli-auth/", () =>
        HttpResponse.json({
          codex: { authenticated: true, auth_status: "ok", auth_file_exists: true },
          claude: { authenticated: false, auth_status: "not_initialized", auth_file_exists: false },
        }),
      ),
      http.get("/api/rest/git-credentials/", () => HttpResponse.json({ configured: false, configured_hosts: [] })),
    );

    renderWithProviders(<SetupPage />);

    expect(await screen.findByText("Codex")).toBeInTheDocument();
    expect(await screen.findByText("Claude")).toBeInTheDocument();
    expect(await screen.findByText("Токен не задан")).toBeInTheDocument();
  });

  it("показывает баннер ошибки при недоступности backend и позволяет повторить запрос", async () => {
    server.use(
      http.get("/api/rest/cli-auth/", () => HttpResponse.json({ detail: "internal error" }, { status: 500 })),
      http.get("/api/rest/git-credentials/", () => HttpResponse.json({ configured: false, configured_hosts: [] })),
    );

    renderWithProviders(<SetupPage />);

    expect(await screen.findByText("Ошибка сервера")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument();
  });
});
