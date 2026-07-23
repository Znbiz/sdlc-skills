import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test/render";
import type { RepositoryStatusResponse } from "../../shared/api/models";
import { ConversationRepositories } from "./conversation-repositories";

const { getRepositoriesMock, addRepositoryMock, removeRepositoryMock, submitActionMock } = vi.hoisted(() => ({
  getRepositoriesMock: vi.fn(),
  addRepositoryMock: vi.fn(),
  removeRepositoryMock: vi.fn(),
  submitActionMock: vi.fn(),
}));

vi.mock("../../shared/api/endpoints", () => ({
  conversationsApi: {
    getRepositories: getRepositoriesMock,
    addRepository: addRepositoryMock,
    removeRepository: removeRepositoryMock,
  },
  workflowApi: {
    submitAction: submitActionMock,
  },
}));

function makeCommit(overrides: Partial<RepositoryStatusResponse> = {}): RepositoryStatusResponse {
  return {
    repository_name: "svc-a",
    repository_url: "https://github.com/org/svc-a.git",
    main_branch: "main",
    remote_head_commit: "abcdef1234567890",
    remote_head_commit_date: "2026-07-20",
    analysis_target_commit: "1234567890abcdef",
    analysis_target_commit_date: "2026-07-01",
    analysis_status: "pending",
    commit_range_status: "not_started",
    ...overrides,
  };
}

describe("ConversationRepositories", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("показывает список репозиториев проекта", async () => {
    getRepositoriesMock.mockResolvedValue([
      { repository_name: "svc-a", repository_url: "https://github.com/org/svc-a.git" },
    ]);
    renderWithProviders(<ConversationRepositories conversationId="conv-1" />);

    expect(await screen.findByText("svc-a")).toBeInTheDocument();
  });

  it("показывает подсказку, если репозиториев ещё нет", async () => {
    getRepositoriesMock.mockResolvedValue([]);
    renderWithProviders(<ConversationRepositories conversationId="conv-1" />);

    expect(await screen.findByText("Репозитории ещё не добавлены.")).toBeInTheDocument();
  });

  it("ввод и клик «Добавить» вызывает conversationsApi.addRepository", async () => {
    getRepositoriesMock.mockResolvedValue([]);
    addRepositoryMock.mockResolvedValue([{ repository_name: "svc-b", repository_url: "" }]);
    const user = userEvent.setup();
    renderWithProviders(<ConversationRepositories conversationId="conv-1" />);

    await screen.findByText("Репозитории ещё не добавлены.");
    await user.type(screen.getByPlaceholderText(/URL или имя репозитория/), "svc-b");
    await user.click(screen.getByRole("button", { name: "Добавить" }));

    expect(addRepositoryMock).toHaveBeenCalledWith("conv-1", "svc-b");
  });

  it("вставка списка репозиториев разворачивает поле в N отдельных инпутов с заполненными значениями", async () => {
    getRepositoriesMock.mockResolvedValue([]);
    addRepositoryMock.mockResolvedValue([]);
    const user = userEvent.setup();
    renderWithProviders(<ConversationRepositories conversationId="conv-1" />);

    await screen.findByText("Репозитории ещё не добавлены.");
    const firstInput = screen.getByPlaceholderText(/URL или имя репозитория/);
    await user.click(firstInput);
    await user.paste("svc-a\nsvc-b, svc-c");

    const rows = screen.getAllByRole("textbox");
    expect(rows).toHaveLength(3);
    expect(rows.map((row) => (row as HTMLInputElement).value)).toEqual(["svc-a", "svc-b", "svc-c"]);
    expect(screen.getByRole("button", { name: "Добавить (3)" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Добавить (3)" }));

    expect(addRepositoryMock).toHaveBeenNthCalledWith(1, "conv-1", "svc-a");
    expect(addRepositoryMock).toHaveBeenNthCalledWith(2, "conv-1", "svc-b");
    expect(addRepositoryMock).toHaveBeenNthCalledWith(3, "conv-1", "svc-c");
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(screen.getByRole("textbox")).toHaveValue("");
  });

  it("кнопка «+ ещё репозиторий» добавляет пустое поле вручную", async () => {
    getRepositoriesMock.mockResolvedValue([]);
    const user = userEvent.setup();
    renderWithProviders(<ConversationRepositories conversationId="conv-1" />);

    await screen.findByText("Репозитории ещё не добавлены.");
    await user.click(screen.getByRole("button", { name: "+ ещё репозиторий" }));

    expect(screen.getAllByRole("textbox")).toHaveLength(2);
  });

  it("клик «Удалить» вызывает conversationsApi.removeRepository с именем репозитория", async () => {
    getRepositoriesMock.mockResolvedValue([
      { repository_name: "svc-a", repository_url: "https://github.com/org/svc-a.git" },
    ]);
    removeRepositoryMock.mockResolvedValue([]);
    const user = userEvent.setup();
    renderWithProviders(<ConversationRepositories conversationId="conv-1" />);

    await user.click(await screen.findByRole("button", { name: "Удалить" }));

    expect(removeRepositoryMock).toHaveBeenCalledWith("conv-1", "svc-a");
  });

  it("если выбран прогон, но список не редактируется, репозитории проекта обогащаются коммитами из прогона", async () => {
    getRepositoriesMock.mockResolvedValue([
      { repository_name: "svc-a", repository_url: "https://github.com/org/svc-a.git" },
    ]);
    renderWithProviders(
      <ConversationRepositories
        conversationId="conv-1"
        run={{ responseId: "wf-1", editable: false, repositories: [makeCommit()] }}
      />,
    );

    expect(await screen.findByText("svc-a")).toBeInTheDocument();
    expect(screen.getByText("abcdef12")).toBeInTheDocument();
    expect(screen.getByText("2026-07-20")).toBeInTheDocument();
    expect(screen.getByText("12345678")).toBeInTheDocument();

    // список не редактируется прогоном - удаление всё ещё идёт через conversationsApi
    await userEvent.setup().click(screen.getByRole("button", { name: "Удалить" }));
    expect(removeRepositoryMock).toHaveBeenCalledWith("conv-1", "svc-a");
    expect(submitActionMock).not.toHaveBeenCalled();
  });

  it("пока прогон на паузе на шаге клонирования (editable), список репозиториев берётся из прогона и правится через submitAction", async () => {
    const user = userEvent.setup();
    submitActionMock.mockResolvedValue({});
    renderWithProviders(
      <ConversationRepositories
        conversationId="conv-1"
        run={{ responseId: "wf-1", editable: true, repositories: [makeCommit()] }}
      />,
    );

    expect(screen.getByText("svc-a")).toBeInTheDocument();
    expect(screen.getByText("abcdef12")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Удалить" }));
    expect(submitActionMock).toHaveBeenCalledWith(
      "wf-1",
      expect.objectContaining({ actionType: "remove_repository", value: "svc-a" }),
    );
    expect(removeRepositoryMock).not.toHaveBeenCalled();

    await user.type(screen.getByPlaceholderText("URL или имя репозитория"), "svc-b");
    await user.click(screen.getByRole("button", { name: "Добавить" }));
    expect(submitActionMock).toHaveBeenCalledWith(
      "wf-1",
      expect.objectContaining({ actionType: "add_repository", value: "svc-b" }),
    );
  });
});
