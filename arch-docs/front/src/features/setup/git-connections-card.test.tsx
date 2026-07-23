import { HttpResponse, http } from "msw";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { server } from "../../test/msw-server";
import { renderWithProviders } from "../../test/render";
import { GitConnectionsCard } from "./git-connections-card";

const PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... arch-docs-service";
const GITHUB_ID = "11111111-1111-1111-1111-111111111111";

function mockGitConnections(connections: { connection_id: string; host: string; connection_type: "token" | "ssh" }[] = []) {
  return http.get("/api/rest/git-connections/", () => HttpResponse.json(connections));
}

function mockGitSshPublicKey() {
  return http.get("/api/rest/git-ssh/public-key/", () => HttpResponse.json({ public_key: PUBLIC_KEY }));
}

describe("GitConnectionsCard", () => {
  it("показывает пустое состояние без подключений", async () => {
    server.use(mockGitConnections(), mockGitSshPublicKey());

    renderWithProviders(<GitConnectionsCard />);

    expect(await screen.findByText("Пока нет подключённых Git-систем")).toBeInTheDocument();
  });

  it("показывает список подключений с типом каждого", async () => {
    server.use(
      mockGitConnections([
        { connection_id: GITHUB_ID, host: "github.com", connection_type: "token" },
        { connection_id: "22222222-2222-2222-2222-222222222222", host: "example.org", connection_type: "ssh" },
      ]),
      mockGitSshPublicKey(),
    );

    renderWithProviders(<GitConnectionsCard />);

    expect(await screen.findByText("github.com")).toBeInTheDocument();
    expect(screen.getByText("Token")).toBeInTheDocument();
    expect(screen.getByText("example.org")).toBeInTheDocument();
    expect(screen.getByText("SSH")).toBeInTheDocument();
  });

  it("создаёт новую token-интеграцию через модалку (POST без id)", async () => {
    server.use(
      mockGitConnections(),
      mockGitSshPublicKey(),
      http.post("/api/rest/git-connections/", async ({ request }) => {
        const body = (await request.json()) as { host: string; connection_type: string; token?: string };
        expect(body).toMatchObject({ host: "gitlab.com", connection_type: "token", token: "glpat-xyz" });
        return HttpResponse.json({ connection_id: GITHUB_ID, host: "gitlab.com", connection_type: "token" }, { status: 201 });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<GitConnectionsCard />);

    await screen.findByText("Пока нет подключённых Git-систем");
    await user.click(screen.getByRole("button", { name: "Новая интеграция" }));

    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByPlaceholderText("github.com"), "gitlab.com");
    await user.type(within(dialog).getByPlaceholderText("ghp_…"), "glpat-xyz");
    await user.click(within(dialog).getByRole("button", { name: "Создать" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("нормализует полный URL в поле «Хост» до голого домена перед отправкой", async () => {
    server.use(
      mockGitConnections(),
      mockGitSshPublicKey(),
      http.post("/api/rest/git-connections/", async ({ request }) => {
        const body = (await request.json()) as { host: string };
        expect(body.host).toBe("gitlab.fssoft.ru");
        return HttpResponse.json({ connection_id: GITHUB_ID, host: "gitlab.fssoft.ru", connection_type: "ssh" }, { status: 201 });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<GitConnectionsCard />);

    await user.click(screen.getByRole("button", { name: "Новая интеграция" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByPlaceholderText("github.com"), "https://gitlab.fssoft.ru/");
    await user.click(within(dialog).getByRole("radio", { name: "SSH" }));
    await user.click(within(dialog).getByRole("button", { name: "Создать" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("показывает публичный SSH-ключ при выборе SSH в модалке создания", async () => {
    server.use(mockGitConnections(), mockGitSshPublicKey());

    const user = userEvent.setup();
    renderWithProviders(<GitConnectionsCard />);

    await user.click(screen.getByRole("button", { name: "Новая интеграция" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("radio", { name: "SSH" }));

    expect(await within(dialog).findByDisplayValue(PUBLIC_KEY)).toBeInTheDocument();
  });

  it("открывает модалку редактирования с предзаполненным токеном и сохраняет по id (PUT)", async () => {
    server.use(
      mockGitConnections([{ connection_id: GITHUB_ID, host: "github.com", connection_type: "token" }]),
      mockGitSshPublicKey(),
      http.get(`/api/rest/git-connections/${GITHUB_ID}/`, () =>
        HttpResponse.json({
          connection_id: GITHUB_ID,
          host: "github.com",
          connection_type: "token",
          token: "ghp_existing",
          username: "custom",
        }),
      ),
      http.put(`/api/rest/git-connections/${GITHUB_ID}/`, async ({ request }) => {
        const body = (await request.json()) as { host: string; connection_type: string };
        expect(body).toMatchObject({ host: "github.com", connection_type: "token" });
        return HttpResponse.json({ connection_id: GITHUB_ID, host: "github.com", connection_type: "token" });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<GitConnectionsCard />);

    await user.click(await screen.findByRole("button", { name: "Редактировать github.com" }));

    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByDisplayValue("ghp_existing")).toBeInTheDocument();
    expect(within(dialog).getByDisplayValue("custom")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("удаляет подключение по id по клику на крестик", async () => {
    let connections = [{ connection_id: GITHUB_ID, host: "github.com", connection_type: "token" as const }];
    server.use(
      http.get("/api/rest/git-connections/", () => HttpResponse.json(connections)),
      mockGitSshPublicKey(),
      http.delete(`/api/rest/git-connections/${GITHUB_ID}/`, () => {
        connections = [];
        return new HttpResponse(null, { status: 204 });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<GitConnectionsCard />);

    await user.click(await screen.findByRole("button", { name: "Удалить github.com" }));

    await waitFor(() => expect(screen.queryByText("github.com")).not.toBeInTheDocument());
  });
});
