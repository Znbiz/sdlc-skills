import { HttpResponse, http } from "msw";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { server } from "../../test/msw-server";
import { renderWithProviders } from "../../test/render";
import { LlmProvidersCard } from "./llm-providers-card";

const CONNECTION_ID = "11111111-1111-1111-1111-111111111111";

function mockLlmProviderConnections(
  connections: { connection_id: string; name: string; model: string }[] = [],
) {
  return http.get("/api/rest/llm-providers/", () =>
    HttpResponse.json(
      connections.map((connection) => ({
        connection_id: connection.connection_id,
        name: connection.name,
        base_url: "https://api.example.com/v1",
        model: connection.model,
        wire_api: "chat",
        requires_openai_auth: false,
      })),
    ),
  );
}

describe("LlmProvidersCard", () => {
  it("показывает пустое состояние без подключений", async () => {
    server.use(mockLlmProviderConnections());

    renderWithProviders(<LlmProvidersCard />);

    expect(await screen.findByText("Пока нет подключённых внешних LLM")).toBeInTheDocument();
  });

  it("показывает список подключений с моделью каждого", async () => {
    server.use(mockLlmProviderConnections([{ connection_id: CONNECTION_ID, name: "my-provider", model: "my-model" }]));

    renderWithProviders(<LlmProvidersCard />);

    expect(await screen.findByText("my-provider")).toBeInTheDocument();
    expect(screen.getByText("my-model")).toBeInTheDocument();
  });

  it("создаёт новое подключение через модалку (POST без id)", async () => {
    server.use(
      mockLlmProviderConnections(),
      http.post("/api/rest/llm-providers/", async ({ request }) => {
        const body = (await request.json()) as { name: string; base_url: string; model: string; token: string };
        expect(body).toMatchObject({
          name: "my-provider",
          base_url: "https://api.example.com/v1",
          model: "my-model",
          token: "sk-abc",
        });
        return HttpResponse.json(
          {
            connection_id: CONNECTION_ID,
            name: "my-provider",
            base_url: "https://api.example.com/v1",
            model: "my-model",
            wire_api: "chat",
            requires_openai_auth: false,
          },
          { status: 201 },
        );
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<LlmProvidersCard />);

    await screen.findByText("Пока нет подключённых внешних LLM");
    await user.click(screen.getByRole("button", { name: "Новое подключение" }));

    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByPlaceholderText("my-provider"), "my-provider");
    await user.type(within(dialog).getByPlaceholderText("https://api.example.com/v1"), "https://api.example.com/v1");
    await user.type(within(dialog).getByPlaceholderText("my-model"), "my-model");
    await user.type(within(dialog).getByPlaceholderText("sk-…"), "sk-abc");
    await user.click(within(dialog).getByRole("button", { name: "Создать" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("открывает модалку редактирования с предзаполненными полями и сохраняет по id (PUT)", async () => {
    server.use(
      mockLlmProviderConnections([{ connection_id: CONNECTION_ID, name: "my-provider", model: "my-model" }]),
      http.get(`/api/rest/llm-providers/${CONNECTION_ID}/`, () =>
        HttpResponse.json({
          connection_id: CONNECTION_ID,
          name: "my-provider",
          base_url: "https://api.example.com/v1",
          model: "my-model",
          wire_api: "chat",
          requires_openai_auth: false,
          token: "********",
        }),
      ),
      http.put(`/api/rest/llm-providers/${CONNECTION_ID}/`, async ({ request }) => {
        const body = (await request.json()) as { name: string };
        expect(body.name).toBe("my-provider");
        return HttpResponse.json({
          connection_id: CONNECTION_ID,
          name: "my-provider",
          base_url: "https://api.example.com/v1",
          model: "my-model",
          wire_api: "chat",
          requires_openai_auth: false,
        });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<LlmProvidersCard />);

    await user.click(await screen.findByRole("button", { name: "Редактировать my-provider" }));

    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByDisplayValue("https://api.example.com/v1")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("удаляет подключение по id по клику на крестик", async () => {
    let connections = [{ connection_id: CONNECTION_ID, name: "my-provider", model: "my-model" }];
    server.use(
      http.get("/api/rest/llm-providers/", () =>
        HttpResponse.json(
          connections.map((connection) => ({
            connection_id: connection.connection_id,
            name: connection.name,
            base_url: "https://api.example.com/v1",
            model: connection.model,
            wire_api: "chat",
            requires_openai_auth: false,
          })),
        ),
      ),
      http.delete(`/api/rest/llm-providers/${CONNECTION_ID}/`, () => {
        connections = [];
        return new HttpResponse(null, { status: 204 });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<LlmProvidersCard />);

    await user.click(await screen.findByRole("button", { name: "Удалить my-provider" }));

    await waitFor(() => expect(screen.queryByText("my-provider")).not.toBeInTheDocument());
  });

  it("показывает успешный результат проверки подключения", async () => {
    server.use(
      mockLlmProviderConnections([{ connection_id: CONNECTION_ID, name: "my-provider", model: "my-model" }]),
      http.post(`/api/rest/llm-providers/${CONNECTION_ID}/test/`, () =>
        HttpResponse.json({ success: true, status_code: 200, message: "Подключение работает" }),
      ),
    );

    const user = userEvent.setup();
    renderWithProviders(<LlmProvidersCard />);

    await user.click(await screen.findByRole("button", { name: "Проверить" }));

    expect(await screen.findByText("✓ Подключение работает")).toBeInTheDocument();
  });

  it("показывает сообщение об ошибке при неудачной проверке подключения", async () => {
    server.use(
      mockLlmProviderConnections([{ connection_id: CONNECTION_ID, name: "my-provider", model: "my-model" }]),
      http.post(`/api/rest/llm-providers/${CONNECTION_ID}/test/`, () =>
        HttpResponse.json({ success: false, status_code: 401, message: "invalid api key" }),
      ),
    );

    const user = userEvent.setup();
    renderWithProviders(<LlmProvidersCard />);

    await user.click(await screen.findByRole("button", { name: "Проверить" }));

    expect(await screen.findByText("✗ invalid api key")).toBeInTheDocument();
  });
});
