import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { server } from "../../test/msw-server";
import { renderWithProviders as render } from "../../test/render";
import { InitArchForm } from "./init-arch-form";

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

describe("InitArchForm", () => {
  beforeEach(() => {
    server.use(mockLlmProviderConnections());
  });

  it("показывает название продукта из проекта как read-only, без поля ввода", () => {
    const onSubmit = vi.fn();
    render(
      <InitArchForm
        isSubmitting={false}
        onSubmit={onSubmit}
        defaultWorkspaceDir="/workspace/conv-1"
        productName="Arch Docs Gateway"
        repositoryNames={["svc-a"]}
      />,
    );

    expect(screen.getByText("Arch Docs Gateway")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /название продукта/i })).not.toBeInTheDocument();
  });

  it("блокирует сабмит, если у проекта нет репозиториев", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <InitArchForm
        isSubmitting={false}
        onSubmit={onSubmit}
        defaultWorkspaceDir="/workspace/conv-1"
        productName="TestProduct"
        repositoryNames={[]}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Запустить init_arch" }));

    expect(await screen.findByText("Добавьте хотя бы один репозиторий проекта в колонке слева.")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("показывает список репозиториев проекта как read-only превью", () => {
    const onSubmit = vi.fn();
    render(
      <InitArchForm
        isSubmitting={false}
        onSubmit={onSubmit}
        defaultWorkspaceDir="/workspace/conv-1"
        productName="TestProduct"
        repositoryNames={["svc-a", "svc-b"]}
      />,
    );

    expect(screen.getByText("svc-a")).toBeInTheDocument();
    expect(screen.getByText("svc-b")).toBeInTheDocument();
  });

  it("блокирует сабмит при некорректном таймауте", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <InitArchForm
        isSubmitting={false}
        onSubmit={onSubmit}
        defaultWorkspaceDir="/workspace/conv-1"
        productName="TestProduct"
        repositoryNames={["svc-a"]}
      />,
    );

    const timeoutInput = screen.getByLabelText("Таймаут шага, сек");
    await user.clear(timeoutInput);
    await user.type(timeoutInput, "0");
    await user.click(screen.getByRole("button", { name: "Запустить init_arch" }));

    expect(await screen.findByText("Таймаут шага должен быть целым числом больше нуля.")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("отправляет валидный input с product_name проекта, analysis_scope='full' и дефолтным workspace_dir", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <InitArchForm
        isSubmitting={false}
        onSubmit={onSubmit}
        defaultWorkspaceDir="/workspace/conv-1"
        productName="TestProduct"
        repositoryNames={["svc-a"]}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Запустить init_arch" }));

    expect(onSubmit).toHaveBeenCalledWith({
      product_name: "TestProduct",
      analysis_scope: "full",
      workspace_dir: "/workspace/conv-1",
      arch_repo_dir: "",
      engine_name: "claude",
      timeout_seconds: 900,
    });
    expect(screen.queryByText(/analysis_scope/i)).not.toBeInTheDocument();
  });

  it("отправляет значения из Advanced-секции, если они изменены", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <InitArchForm
        isSubmitting={false}
        onSubmit={onSubmit}
        defaultWorkspaceDir="/workspace/conv-1"
        productName="TestProduct"
        repositoryNames={["svc-a"]}
      />,
    );

    await user.click(screen.getByText("Advanced"));

    const workspaceDirInput = screen.getByLabelText("Workspace dir");
    await user.clear(workspaceDirInput);
    await user.type(workspaceDirInput, "/workspace/custom");

    const archRepoDirInput = screen.getByLabelText("Arch repo dir");
    await user.type(archRepoDirInput, "/workspace/custom/arch-doc");

    await user.selectOptions(screen.getByLabelText("Движок"), "codex");

    await user.click(screen.getByRole("button", { name: "Запустить init_arch" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        workspace_dir: "/workspace/custom",
        arch_repo_dir: "/workspace/custom/arch-doc",
        engine_name: "codex",
      }),
    );
  });

  it("блокирует кнопку сабмита во время отправки", () => {
    const onSubmit = vi.fn();
    render(
      <InitArchForm
        isSubmitting={true}
        onSubmit={onSubmit}
        defaultWorkspaceDir="/workspace/conv-1"
        productName="TestProduct"
        repositoryNames={["svc-a"]}
      />,
    );

    expect(screen.getByRole("button", { name: "Запустить init_arch" })).toBeDisabled();
  });

  it("предзаполняет пути из previousInput (после restart), но product_name берёт из проекта", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <InitArchForm
        isSubmitting={false}
        onSubmit={onSubmit}
        defaultWorkspaceDir="/workspace/conv-1"
        productName="Renamed Project"
        repositoryNames={["svc-a"]}
        previousInput={{
          product_name: "RestartedProduct",
          analysis_scope: "full",
          workspace_dir: "/workspace/restarted",
          arch_repo_dir: "/workspace/restarted/arch-doc",
        }}
      />,
    );

    expect(screen.getByText("Renamed Project")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Запустить init_arch" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        product_name: "Renamed Project",
        workspace_dir: "/workspace/restarted",
        arch_repo_dir: "/workspace/restarted/arch-doc",
      }),
    );
  });

  it("без previousInput использует дефолтный workspace_dir проекта", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(
      <InitArchForm
        isSubmitting={false}
        onSubmit={onSubmit}
        previousInput={null}
        defaultWorkspaceDir="/workspace/conv-1"
        productName="TestProduct"
        repositoryNames={[]}
      />,
    );

    await user.click(screen.getByText("Advanced"));
    expect(screen.getByLabelText("Workspace dir")).toHaveValue("/workspace/conv-1");
  });

  it("блокирует сабмит с внешней LLM без выбранного подключения", async () => {
    server.use(mockLlmProviderConnections([]));
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <InitArchForm
        isSubmitting={false}
        onSubmit={onSubmit}
        defaultWorkspaceDir="/workspace/conv-1"
        productName="TestProduct"
        repositoryNames={["svc-a"]}
      />,
    );

    await user.selectOptions(screen.getByLabelText("Движок"), "external");
    expect(await screen.findByText("Нет настроенных подключений — добавьте их в Setup перед запуском.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Запустить init_arch" }));

    expect(
      await screen.findByText("Выберите подключение к внешней LLM (или настройте его в Setup)."),
    ).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("отправляет engine_name='codex' и provider_connection_id при выборе внешней LLM", async () => {
    server.use(mockLlmProviderConnections([{ connection_id: "conn-1", name: "my-provider", model: "my-model" }]));
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <InitArchForm
        isSubmitting={false}
        onSubmit={onSubmit}
        defaultWorkspaceDir="/workspace/conv-1"
        productName="TestProduct"
        repositoryNames={["svc-a"]}
      />,
    );

    await user.selectOptions(screen.getByLabelText("Движок"), "external");
    await screen.findByText("my-provider (my-model)");
    await user.selectOptions(screen.getByLabelText("Подключение к внешней LLM"), "conn-1");

    await user.click(screen.getByRole("button", { name: "Запустить init_arch" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        engine_name: "codex",
        provider_connection_id: "conn-1",
      }),
    );
  });
});
