import { useMemo } from "react";
import ReactFlow, { Background, MarkerType, type Edge, type Node } from "reactflow";
import "reactflow/dist/style.css";
import type { RepositoryStatusResponse } from "../../shared/api/models";
import { formatDate } from "../../shared/format/format";
import { CHECKLIST_ITEMS, DONE_NODE_ID, GRAPH_EDGES, GRAPH_NODES, HANDLE_ERROR_NODE_ID } from "./workflow-graph-data";
import styles from "./workflow-graph.module.css";

export { HANDLE_ERROR_NODE_ID, DONE_NODE_ID };

export function resolveActiveGraphNodeId({
  hasStepFailedAction,
  responseStatus,
  currentStepId,
}: {
  hasStepFailedAction: boolean;
  responseStatus: string;
  currentStepId: string;
}): string {
  if (hasStepFailedAction) return HANDLE_ERROR_NODE_ID;
  if (responseStatus === "success") return DONE_NODE_ID;
  return currentStepId || GRAPH_NODES[0].id;
}

export function formatAnalysisWindowLabel({
  analysisWindowStart,
  analysisWindowEnd,
  analysisWindowIndex,
}: {
  analysisWindowStart: string | null;
  analysisWindowEnd: string | null;
  analysisWindowIndex: number;
}): string {
  if (!analysisWindowEnd) return "Период анализа пока не определён";
  const start = analysisWindowStart ? formatDate(analysisWindowStart) : "начало истории";
  const end = formatDate(analysisWindowEnd);
  const windowLabel = analysisWindowIndex > 0 ? ` · окно №${analysisWindowIndex + 1}` : "";
  return `Период анализа: ${start} – ${end}${windowLabel}`;
}

type ChecklistItemStatus = "completed" | "current" | "pending" | "not_routed";

function checklistItemStatus(
  itemId: string,
  repository: RepositoryStatusResponse,
): ChecklistItemStatus {
  if (repository.checklist_items_completed.includes(itemId)) return "completed";
  if (repository.current_checklist_item_id === itemId) return "current";
  if (repository.checklist_items_routed.length > 0 && !repository.checklist_items_routed.includes(itemId)) {
    return "not_routed";
  }
  return "pending";
}

const CHECKLIST_STATUS_MARK: Record<ChecklistItemStatus, string> = {
  completed: "✓",
  current: "…",
  pending: "○",
  not_routed: "—",
};

function RepositoryChecklistCard({ repository }: { repository: RepositoryStatusResponse }) {
  return (
    <div className={styles.repositoryCard}>
      <div className={styles.repositoryCardHeader}>
        <span className={styles.repositoryCardName}>{repository.repository_name}</span>
        <span className={styles.repositoryCardStatus}>{repository.analysis_status}</span>
      </div>
      <ul className={styles.checklist}>
        {CHECKLIST_ITEMS.map((item) => {
          const itemStatus = checklistItemStatus(item.id, repository);
          return (
            <li
              key={item.id}
              className={
                itemStatus === "current"
                  ? styles.checklistItemCurrent
                  : itemStatus === "not_routed"
                    ? styles.checklistItemNotRouted
                    : itemStatus === "completed"
                      ? styles.checklistItemCompleted
                      : styles.checklistItem
              }
            >
              <span className={styles.checklistItemMark}>{CHECKLIST_STATUS_MARK[itemStatus]}</span>
              <span>{item.label}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function RepositoryChecklistsPanel({ repositories }: { repositories: RepositoryStatusResponse[] }) {
  if (repositories.length === 0) return null;
  return (
    <div className={styles.repositoryChecklists}>
      {repositories.map((repository) => (
        <RepositoryChecklistCard key={repository.repository_name} repository={repository} />
      ))}
    </div>
  );
}

export function WorkflowGraphView({
  activeNodeId,
  repositories = [],
  analysisWindowStart = null,
  analysisWindowEnd = null,
  analysisWindowIndex = 0,
}: {
  activeNodeId: string;
  repositories?: RepositoryStatusResponse[];
  analysisWindowStart?: string | null;
  analysisWindowEnd?: string | null;
  analysisWindowIndex?: number;
}) {
  const nodes: Node[] = useMemo(
    () =>
      GRAPH_NODES.map((node) => ({
        id: node.id,
        position: { x: node.x, y: node.y },
        data: { label: node.label },
        className: node.id === activeNodeId ? styles.activeNode : styles.node,
        style: { whiteSpace: "pre-line" },
      })),
    [activeNodeId],
  );

  const edges: Edge[] = useMemo(
    () =>
      GRAPH_EDGES.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: edge.label,
        style: edge.dashed ? { strokeDasharray: "4 4" } : undefined,
        labelStyle: { fontSize: 11 },
        markerEnd: { type: MarkerType.ArrowClosed },
      })),
    [],
  );

  return (
    <div>
      <p className={styles.analysisWindow}>
        {formatAnalysisWindowLabel({ analysisWindowStart, analysisWindowEnd, analysisWindowIndex })}
      </p>
      <div className={styles.canvas}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background />
        </ReactFlow>
      </div>
      <RepositoryChecklistsPanel repositories={repositories} />
    </div>
  );
}
