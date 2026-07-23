import { HttpResponse, http } from "msw";
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { server } from "../../test/msw-server";
import { renderWithProviders } from "../../test/render";
import { SetupPage } from "./setup-page";

const PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... arch-docs-service";

function mockCliAuth() {
  return http.get("/api/rest/cli-auth/", () =>
    HttpResponse.json({
      codex: { authenticated: true, auth_status: "ok", auth_file_exists: true },
      claude: { authenticated: false, auth_status: "not_initialized", auth_file_exists: false },
    }),
  );
}

function mockGitConnections(connections: { host: string; connection_type: "token" | "ssh" }[] = []) {
  return http.get("/api/rest/git-connections/", () => HttpResponse.json(connections));
}

function mockGitSshPublicKey() {
  return http.get("/api/rest/git-ssh/public-key/", () => HttpResponse.json({ public_key: PUBLIC_KEY }));
}

describe("SetupPage", () => {
  it("показывает статус авторизации обоих CLI-агентов и список Git-подключений", async () => {
    server.use(mockCliAuth(), mockGitConnections(), mockGitSshPublicKey());

    renderWithProviders(<SetupPage />);

    expect(await screen.findByText("Codex")).toBeInTheDocument();
    expect(await screen.findByText("Claude")).toBeInTheDocument();
    expect(await screen.findByText("Git-подключения")).toBeInTheDocument();
    expect(await screen.findByText("Пока нет подключённых Git-систем")).toBeInTheDocument();
  });

  it("показывает баннер ошибки при недоступности backend и позволяет повторить запрос", async () => {
    server.use(
      http.get("/api/rest/cli-auth/", () => HttpResponse.json({ detail: "internal error" }, { status: 500 })),
      mockGitConnections(),
      mockGitSshPublicKey(),
    );

    renderWithProviders(<SetupPage />);

    expect(await screen.findByText("Ошибка сервера")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument();
  });
});
