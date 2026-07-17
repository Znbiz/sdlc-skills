import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test/render";
import type { RequiredActionResponse } from "../../shared/api/models";
import { RequiredActionCard } from "./required-action-card";

const { submitActionMock } = vi.hoisted(() => ({ submitActionMock: vi.fn() }));

vi.mock("../../shared/api/endpoints", () => ({
  workflowApi: {
    submitAction: submitActionMock,
  },
}));

function makeStepFailedAction(overrides: Partial<RequiredActionResponse["payload"]> = {}): RequiredActionResponse {
  return {
    action_type: "step_failed",
    question_id: null,
    action_status: "pending",
    payload: {
      step_id: "clone_repositories",
      step_title: "Clone repositories",
      error: "git clone failed: repository not found",
      retry_count: 3,
      ...overrides,
    },
  };
}

describe("RequiredActionCard step_failed", () => {
  it("показывает шаг, полный текст ошибки и число попыток", () => {
    renderWithProviders(
      <RequiredActionCard responseId="wf-1" conversationId="conv-1" action={makeStepFailedAction()} />,
    );

    expect(screen.getByText(/Clone repositories/)).toBeInTheDocument();
    expect(screen.getByText(/clone_repositories/)).toBeInTheDocument();
    expect(screen.getByText(/git clone failed: repository not found/)).toBeInTheDocument();
    expect(screen.getByText(/3/)).toBeInTheDocument();
  });

  it("клик «Повторить» отправляет actionType retry без value", async () => {
    submitActionMock.mockResolvedValue({});
    const user = userEvent.setup();
    renderWithProviders(
      <RequiredActionCard responseId="wf-1" conversationId="conv-1" action={makeStepFailedAction()} />,
    );

    await user.click(screen.getByRole("button", { name: "Повторить" }));

    expect(submitActionMock).toHaveBeenCalledWith("wf-1", { responseId: "wf-1", actionType: "retry" });
  });

  it("клик «Прервать» отправляет actionType retry с value=abort", async () => {
    submitActionMock.mockResolvedValue({});
    const user = userEvent.setup();
    renderWithProviders(
      <RequiredActionCard responseId="wf-1" conversationId="conv-1" action={makeStepFailedAction()} />,
    );

    await user.click(screen.getByRole("button", { name: "Прервать" }));

    expect(submitActionMock).toHaveBeenCalledWith(
      "wf-1",
      expect.objectContaining({ actionType: "retry", value: "abort" }),
    );
  });
});
