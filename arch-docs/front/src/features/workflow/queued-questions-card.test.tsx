import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { RequiredActionResponse } from "../../shared/api/models";
import { QueuedQuestionsCard } from "./queued-questions-card";

function makeQueuedQuestion(questionId: string, questionText: string): RequiredActionResponse {
  return {
    action_type: "user_question",
    question_id: questionId,
    action_status: "open",
    payload: { question_id: questionId, question_text: questionText, status: "open" },
  };
}

describe("QueuedQuestionsCard", () => {
  it("ничего не рендерит при пустом списке", () => {
    const { container } = render(<QueuedQuestionsCard questions={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("показывает счётчик и текст каждого вопроса из очереди", () => {
    render(
      <QueuedQuestionsCard
        questions={[
          makeQueuedQuestion("q-1", "Какие поля оплаты отображает внешний UI?"),
          makeQueuedQuestion("q-2", "Как ограничивается доступ к provisioning-экранам?"),
        ]}
      />,
    );

    expect(screen.getByText("Открытые вопросы в очереди (2)")).toBeInTheDocument();
    expect(screen.getByText("Какие поля оплаты отображает внешний UI?")).toBeInTheDocument();
    expect(screen.getByText("Как ограничивается доступ к provisioning-экранам?")).toBeInTheDocument();
  });
});
