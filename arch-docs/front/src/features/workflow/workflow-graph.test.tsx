import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import type { RepositoryStatusResponse } from "../../shared/api/models";
import {
  DONE_NODE_ID,
  formatAnalysisWindowLabel,
  HANDLE_ERROR_NODE_ID,
  RepositoryChecklistsPanel,
  resolveActiveGraphNodeId,
  WorkflowGraphView,
} from "./workflow-graph";
import styles from "./workflow-graph.module.css";

function makeRepository(overrides: Partial<RepositoryStatusResponse> = {}): RepositoryStatusResponse {
  return {
    repository_name: "repo-a",
    repository_url: "https://github.com/org/repo-a.git",
    main_branch: "main",
    remote_head_commit: "abc123",
    remote_head_commit_date: null,
    analysis_target_commit: "abc123",
    analysis_target_commit_date: null,
    analysis_status: "in_progress",
    commit_range_status: "not_started",
    checklist_items_completed: [],
    checklist_items_routed: [],
    current_checklist_item_id: null,
    ...overrides,
  };
}

// reactflow measures its container with ResizeObserver, which jsdom doesn't implement.
beforeAll(() => {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  global.ResizeObserver = ResizeObserverStub;
});

describe("resolveActiveGraphNodeId", () => {
  it("подсвечивает handle_error, если есть required_action step_failed, даже если current_step_id иной", () => {
    expect(
      resolveActiveGraphNodeId({
        hasStepFailedAction: true,
        responseStatus: "interrupted",
        currentStepId: "analyze_repositories",
      }),
    ).toBe(HANDLE_ERROR_NODE_ID);
  });

  it("подсвечивает done для завершённого прогона", () => {
    expect(
      resolveActiveGraphNodeId({ hasStepFailedAction: false, responseStatus: "success", currentStepId: "" }),
    ).toBe(DONE_NODE_ID);
  });

  it("иначе использует current_step_id", () => {
    expect(
      resolveActiveGraphNodeId({
        hasStepFailedAction: false,
        responseStatus: "running",
        currentStepId: "analyze_repositories",
      }),
    ).toBe("analyze_repositories");
  });

  it("падает обратно на первый узел графа, если current_step_id пуст", () => {
    expect(
      resolveActiveGraphNodeId({ hasStepFailedAction: false, responseStatus: "running", currentStepId: "" }),
    ).toBe("define_scope");
  });
});

describe("WorkflowGraphView", () => {
  it("подсвечивает активный узел и не подсвечивает остальные", () => {
    const { container } = render(<WorkflowGraphView activeNodeId="analyze_repositories" />);

    const activeNode = container.querySelector('[data-id="analyze_repositories"]');
    const inactiveNode = container.querySelector('[data-id="define_scope"]');

    expect(activeNode).not.toBeNull();
    expect(activeNode?.className).toContain(styles.activeNode);
    expect(inactiveNode?.className).toContain(styles.node);
    expect(inactiveNode?.className).not.toContain(styles.activeNode);
  });

  it("показывает период анализа над графом и чеклист по каждому репозиторию", () => {
    render(
      <WorkflowGraphView
        activeNodeId="analyze_repositories_item"
        repositories={[makeRepository({ repository_name: "repo-a" }), makeRepository({ repository_name: "repo-b" })]}
        analysisWindowStart="2026-01-01"
        analysisWindowEnd="2026-07-01"
        analysisWindowIndex={1}
      />,
    );

    expect(screen.getByText(/Период анализа/)).toBeInTheDocument();
    expect(screen.getByText("repo-a")).toBeInTheDocument();
    expect(screen.getByText("repo-b")).toBeInTheDocument();
  });
});

describe("formatAnalysisWindowLabel", () => {
  it("сообщает, что период ещё не определён без конца окна", () => {
    expect(
      formatAnalysisWindowLabel({ analysisWindowStart: null, analysisWindowEnd: null, analysisWindowIndex: 0 }),
    ).toBe("Период анализа пока не определён");
  });

  it("форматирует период с началом истории, если начало окна не задано", () => {
    expect(
      formatAnalysisWindowLabel({
        analysisWindowStart: null,
        analysisWindowEnd: "2026-07-01",
        analysisWindowIndex: 0,
      }),
    ).toContain("начало истории");
  });

  it("добавляет номер окна для повторных прогонов", () => {
    expect(
      formatAnalysisWindowLabel({
        analysisWindowStart: "2026-01-01",
        analysisWindowEnd: "2026-07-01",
        analysisWindowIndex: 1,
      }),
    ).toContain("окно №2");
  });
});

describe("RepositoryChecklistsPanel", () => {
  it("отмечает выполненные и текущий пункт чеклиста для каждого репозитория", () => {
    render(
      <RepositoryChecklistsPanel
        repositories={[
          makeRepository({
            repository_name: "repo-a",
            checklist_items_completed: ["deleted_functionality_cleanup"],
            checklist_items_routed: ["deleted_functionality_cleanup", "repository_classification"],
            current_checklist_item_id: "repository_classification",
          }),
        ]}
      />,
    );

    const completedItem = screen.getByText("Очистка удалённой функциональности").closest("li");
    const currentItem = screen.getByText("Классификация репозитория").closest("li");
    const notRoutedItem = screen.getByText("Технологический стек").closest("li");

    expect(completedItem?.className).toContain(styles.checklistItemCompleted);
    expect(currentItem?.className).toContain(styles.checklistItemCurrent);
    expect(notRoutedItem?.className).toContain(styles.checklistItemNotRouted);
  });

  it("ничего не рендерит без репозиториев", () => {
    const { container } = render(<RepositoryChecklistsPanel repositories={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
