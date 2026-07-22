import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { InitArchForm } from "./init-arch-form";

describe("InitArchForm", () => {
  it("блокирует сабмит и показывает ошибку, если не указано название продукта", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<InitArchForm isSubmitting={false} onSubmit={onSubmit} />);

    await user.type(screen.getByPlaceholderText("https://github.com/org/repo.git"), "org/repo");
    await user.click(screen.getByRole("button", { name: "Запустить init_arch" }));

    expect(await screen.findByText("Укажите название продукта.")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("блокирует сабмит, если ни один репозиторий не заполнен", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<InitArchForm isSubmitting={false} onSubmit={onSubmit} />);

    await user.type(screen.getByPlaceholderText("Arch Docs Gateway"), "TestProduct");
    await user.click(screen.getByRole("button", { name: "Запустить init_arch" }));

    expect(await screen.findByText("Добавьте хотя бы один репозиторий.")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("блокирует сабмит при некорректном таймауте", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<InitArchForm isSubmitting={false} onSubmit={onSubmit} />);

    await user.type(screen.getByPlaceholderText("Arch Docs Gateway"), "TestProduct");
    await user.type(screen.getByPlaceholderText("https://github.com/org/repo.git"), "org/repo");
    const timeoutInput = screen.getByLabelText("Таймаут шага, сек");
    await user.clear(timeoutInput);
    await user.type(timeoutInput, "0");
    await user.click(screen.getByRole("button", { name: "Запустить init_arch" }));

    expect(await screen.findByText("Таймаут шага должен быть целым числом больше нуля.")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("отправляет валидный input с analysis_scope='full' без участия пользователя и с дефолтами", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<InitArchForm isSubmitting={false} onSubmit={onSubmit} />);

    await user.type(screen.getByPlaceholderText("Arch Docs Gateway"), "TestProduct");
    await user.type(screen.getByPlaceholderText("https://github.com/org/repo.git"), "https://github.com/org/repo.git");
    await user.click(screen.getByRole("button", { name: "Запустить init_arch" }));

    expect(onSubmit).toHaveBeenCalledWith({
      product_name: "TestProduct",
      analysis_scope: "full",
      workspace_dir: "/workspace",
      arch_repo_dir: "",
      repo_list: ["https://github.com/org/repo.git"],
      engine_name: "claude",
      timeout_seconds: 900,
    });
    expect(screen.queryByText(/analysis_scope/i)).not.toBeInTheDocument();
  });

  it("позволяет добавить и убрать строку репозитория", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<InitArchForm isSubmitting={false} onSubmit={onSubmit} />);

    await user.click(screen.getByRole("button", { name: "Добавить репозиторий" }));
    const repoInputs = screen.getAllByPlaceholderText("https://github.com/org/repo.git");
    expect(repoInputs).toHaveLength(2);

    await user.click(screen.getAllByRole("button", { name: "Убрать" })[1]);
    expect(screen.getAllByPlaceholderText("https://github.com/org/repo.git")).toHaveLength(1);
  });

  it("не даёт убрать последнюю строку репозитория", () => {
    const onSubmit = vi.fn();
    render(<InitArchForm isSubmitting={false} onSubmit={onSubmit} />);

    expect(screen.getByRole("button", { name: "Убрать" })).toBeDisabled();
  });

  it("отправляет значения из Advanced-секции, если они изменены", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<InitArchForm isSubmitting={false} onSubmit={onSubmit} />);

    await user.click(screen.getByText("Advanced"));
    await user.type(screen.getByPlaceholderText("Arch Docs Gateway"), "TestProduct");
    await user.type(screen.getByPlaceholderText("https://github.com/org/repo.git"), "org/repo");

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
    render(<InitArchForm isSubmitting={true} onSubmit={onSubmit} />);

    expect(screen.getByRole("button", { name: "Запустить init_arch" })).toBeDisabled();
  });

  it("предзаполняет поля из previousInput (после restart) и отправляет их как есть", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <InitArchForm
        isSubmitting={false}
        onSubmit={onSubmit}
        previousInput={{
          product_name: "RestartedProduct",
          analysis_scope: "full",
          workspace_dir: "/workspace/restarted",
          arch_repo_dir: "/workspace/restarted/arch-doc",
          repo_list: ["https://github.com/org/repo-a.git", "https://github.com/org/repo-b.git"],
        }}
      />,
    );

    expect(screen.getByPlaceholderText("Arch Docs Gateway")).toHaveValue("RestartedProduct");
    expect(screen.getAllByPlaceholderText("https://github.com/org/repo.git").map((input) => (input as HTMLInputElement).value)).toEqual([
      "https://github.com/org/repo-a.git",
      "https://github.com/org/repo-b.git",
    ]);

    await user.click(screen.getByRole("button", { name: "Запустить init_arch" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        product_name: "RestartedProduct",
        repo_list: ["https://github.com/org/repo-a.git", "https://github.com/org/repo-b.git"],
        workspace_dir: "/workspace/restarted",
        arch_repo_dir: "/workspace/restarted/arch-doc",
      }),
    );
  });

  it("без previousInput ведёт себя как раньше (пустая форма)", () => {
    const onSubmit = vi.fn();
    render(<InitArchForm isSubmitting={false} onSubmit={onSubmit} previousInput={null} />);

    expect(screen.getByPlaceholderText("Arch Docs Gateway")).toHaveValue("");
  });
});
