import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test/render";
import type { ConversationResponse, ResponseStatusResponse } from "../../shared/api/models";
import { ProjectList } from "./project-list";

const { listConversationsMock, submitActionMock, deleteConversationMock, setLastResponseIdMock } = vi.hoisted(() => ({
  listConversationsMock: vi.fn(),
  submitActionMock: vi.fn(),
  deleteConversationMock: vi.fn(),
  setLastResponseIdMock: vi.fn(),
}));

vi.mock("../../shared/api/endpoints", () => ({
  workflowApi: {
    listConversations: listConversationsMock,
    submitAction: submitActionMock,
  },
  conversationsApi: {
    deleteConversation: deleteConversationMock,
  },
}));

vi.mock("../../shared/storage/recent-response", () => ({
  setLastResponseId: setLastResponseIdMock,
  getLastResponseId: vi.fn(() => null),
}));

const { setLastConversationIdMock } = vi.hoisted(() => ({ setLastConversationIdMock: vi.fn() }));

vi.mock("../../shared/storage/recent-conversation", () => ({
  setLastConversationId: setLastConversationIdMock,
  getLastConversationId: vi.fn(() => null),
}));

function makeResponse(overrides: Partial<ResponseStatusResponse> = {}): ResponseStatusResponse {
  return {
    response_id: "wf-1",
    conversation_id: "conv-1",
    workflow_type: "init_arch",
    response_status: "running",
    current_step_id: "clone_repositories",
    current_repo_name: "",
    workspace_dir: "",
    arch_repo_dir: "",
    completed_steps: [],
    required_actions: [],
    repositories: [],
    repository_list_editable: false,
    created_at: "2026-07-22T00:00:00+00:00",
    updated_at: "2026-07-22T00:00:00+00:00",
    error_message: null,
    terminal_result: null,
    ...overrides,
  };
}

function makeConversation(overrides: Partial<ConversationResponse> = {}): ConversationResponse {
  return {
    conversation_id: "conv-1",
    product_name: "Arch Docs Gateway",
    repositories: [],
    workspace_dir: "/workspace/conv-1",
    created_at: "2026-07-22T00:00:00+00:00",
    updated_at: "2026-07-22T00:00:00+00:00",
    active_response: makeResponse(),
    previous_init_input: null,
    ...overrides,
  };
}

describe("ProjectList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("показывает название проекта, id и статус последнего запуска", async () => {
    listConversationsMock.mockResolvedValue([makeConversation()]);
    renderWithProviders(<ProjectList />);

    expect(await screen.findByText("Arch Docs Gateway")).toBeInTheDocument();
    expect(screen.getByText("conv-1")).toBeInTheDocument();
    expect(screen.getByText("Выполняется")).toBeInTheDocument();
    expect(screen.getByText(/clone_repositories/)).toBeInTheDocument();
  });

  it("падает обратно на короткий id, если проект ещё не назван", async () => {
    listConversationsMock.mockResolvedValue([makeConversation({ product_name: null })]);
    renderWithProviders(<ProjectList />);

    expect(await screen.findAllByText("conv-1")).toHaveLength(2);
  });

  it("показывает чипы репозиториев проекта", async () => {
    listConversationsMock.mockResolvedValue([
      makeConversation({ repositories: [{ repository_name: "svc-a", repository_url: "" }, { repository_name: "svc-b", repository_url: "" }] }),
    ]);
    renderWithProviders(<ProjectList />);

    expect(await screen.findByText("svc-a")).toBeInTheDocument();
    expect(screen.getByText("svc-b")).toBeInTheDocument();
  });

  it("фильтрует список по названию репозитория", async () => {
    listConversationsMock.mockResolvedValue([
      makeConversation({ conversation_id: "conv-1", product_name: "First", repositories: [{ repository_name: "svc-a", repository_url: "" }] }),
      makeConversation({ conversation_id: "conv-2", product_name: "Second", active_response: null, repositories: [{ repository_name: "svc-z", repository_url: "" }] }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<ProjectList />);

    await screen.findByText("First");
    await user.type(screen.getByPlaceholderText("Поиск по названию проекта или репозиторию"), "svc-z");

    expect(screen.queryByText("First")).not.toBeInTheDocument();
    expect(screen.getByText("Second")).toBeInTheDocument();
  });

  it("ничего не рендерит, если список пуст", async () => {
    listConversationsMock.mockResolvedValue([]);
    renderWithProviders(<ProjectList />);

    await waitFor(() => expect(listConversationsMock).toHaveBeenCalled());
    expect(screen.queryByText("Проекты")).not.toBeInTheDocument();
  });

  it("клик по строке проекта (не по кнопке) открывает проект", async () => {
    listConversationsMock.mockResolvedValue([makeConversation()]);
    const user = userEvent.setup();
    renderWithProviders(<ProjectList />);

    await user.click(await screen.findByText("Arch Docs Gateway"));

    expect(setLastConversationIdMock).toHaveBeenCalledWith("conv-1");
  });

  it("клик по кнопке действия внутри строки не открывает проект (stopPropagation)", async () => {
    listConversationsMock.mockResolvedValue([makeConversation()]);
    submitActionMock.mockResolvedValue({});
    const user = userEvent.setup();
    renderWithProviders(<ProjectList />);

    await user.click(await screen.findByRole("button", { name: "Пауза" }));

    expect(setLastConversationIdMock).not.toHaveBeenCalled();
  });

  it("для статуса running показывает кнопку «Пауза», отправляющую actionType pause", async () => {
    listConversationsMock.mockResolvedValue([makeConversation()]);
    submitActionMock.mockResolvedValue({});
    const user = userEvent.setup();
    renderWithProviders(<ProjectList />);

    await screen.findByText("Arch Docs Gateway");
    await user.click(screen.getByRole("button", { name: "Пауза" }));

    expect(submitActionMock).toHaveBeenCalledWith("wf-1", expect.objectContaining({ actionType: "pause" }));
  });

  it("кнопка «Удалить» требует подтверждения перед удалением проекта целиком", async () => {
    listConversationsMock.mockResolvedValue([makeConversation({ active_response: makeResponse({ response_status: "paused" }) })]);
    deleteConversationMock.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderWithProviders(<ProjectList />);

    await screen.findByText("Arch Docs Gateway");
    await user.click(screen.getByRole("button", { name: "Удалить" }));
    expect(deleteConversationMock).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Да, удалить проект целиком" }));
    expect(deleteConversationMock).toHaveBeenCalledWith("conv-1");
  });

  it("для conversation без активного response показывает «прогонов ещё не было»", async () => {
    listConversationsMock.mockResolvedValue([makeConversation({ active_response: null })]);
    renderWithProviders(<ProjectList />);

    await screen.findByText("Arch Docs Gateway");
    expect(screen.getByText("прогонов ещё не было")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Пауза" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Удалить" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Документация" })).not.toBeInTheDocument();
  });

  it("кнопка «Документация» ведёт на вкладку Docs с response_id последнего запуска", async () => {
    listConversationsMock.mockResolvedValue([makeConversation()]);
    const user = userEvent.setup();
    renderWithProviders(<ProjectList />);

    await screen.findByText("Arch Docs Gateway");
    await user.click(screen.getByRole("button", { name: "Документация" }));

    expect(setLastResponseIdMock).toHaveBeenCalledWith("wf-1");
  });
});
