import * as yaml from "js-yaml";

// Enum-like types that match the Python model values
export type WorkflowStatusType =
  | "pending"
  | "in_progress"
  | "waiting_for_user"
  | "failed"
  | "completed";

export type StepIdType =
  | "define_scope"
  | "request_repository_list"
  | "prepare_temp_workspace"
  | "clone_repositories"
  | "refresh_main_branches"
  | "plan_repository_order"
  | "assess_scope_and_domains"
  | "analyze_repositories"
  | "interview_user"
  | "refine_features"
  | "build_navigation_index"
  | "run_knowledge_lint"
  | "validate_final"
  | "generate_release_notes"
  | "confirm_next_temporal_window"
  | "finalize_progress"
  | "done";

export type AnalysisTargetCommitStatusType =
  | "pending"
  | "resolved"
  | "missing"
  | "checked_out";

export type CommitRangeStatusType =
  | "not_started"
  | "baseline_missing"
  | "range_resolved"
  | "diff_collected"
  | "no_changes"
  | "invalid_range";

export type DomainStrategyType = "per_module" | "per_domain";

export type NextWindowConfirmationStatusType =
  | "none"
  | "pending"
  | "confirmed"
  | "stopped";

export type OpenQuestionStatusType = "open" | "answered" | "closed";

// Domain-related types
export interface DomainDefinitionShape {
  domain_id: string;
  name: string;
  paths?: string[];
  signal?: string;
  subdomains?: string[];
}

// Repository-related types
export interface RepositoryExecutionShape {
  repository_name: string;
  role?: string;
  repository_url?: string;
  created_at?: string | null;
  main_branch?: string;
  remote_head_commit?: string;
  analysis_target_date?: string | null;
  analysis_target_commit?: string;
  analysis_target_commit_status?: AnalysisTargetCommitStatusType;
  previous_analysis_target_commit?: string;
  window_start_commit?: string;
  window_end_commit?: string;
  commit_range?: string;
  commit_range_status?: CommitRangeStatusType;
  diff_stat_summary?: string;
  commit_log_summary?: string;
  changed_paths?: string[];
  renamed_paths?: string[];
  deleted_paths?: string[];
  temporal_delta_note?: string;
  domain_strategy?: DomainStrategyType | null;
  domains?: DomainDefinitionShape[];
  checklist_items_completed?: string[];
  analysis_status?: "pending" | "in_progress" | "completed";
}

// Historical analysis state
export interface HistoricalAnalysisStateShape {
  anchor_repository_name?: string;
  anchor_created_at?: string | null;
  previous_snapshot_at?: string | null;
  current_snapshot_at?: string | null;
  ordered_repository_names?: string[];
  completed_snapshot_dates?: string[];
  prep_notes?: string;
  window_index?: number;
  awaiting_window_confirmation?: boolean;
  last_completed_snapshot_at?: string | null;
  next_snapshot_at?: string | null;
  next_window_confirmation_status?: NextWindowConfirmationStatusType;
}

// Artifact record
export interface ArtifactRecordShape {
  artifact_path: string;
  artifact_kind: string;
  source_refs?: string[];
  last_updated_step?: StepIdType | null;
  last_updated_window_index?: number;
}

// Open question record
export interface OpenQuestionRecordShape {
  question_id: string;
  question_text: string;
  status?: OpenQuestionStatusType;
  target_artifacts?: string[];
  related_repositories?: string[];
  answer_text?: string;
}

// Session record (contains workflow state)
export interface WorkflowSessionShape {
  session_id: string;
  product_name: string;
  analysis_scope: string;
  status?: WorkflowStatusType;
  current_step?: StepIdType;
  completed_steps?: StepIdType[];
  repositories?: RepositoryExecutionShape[];
  historical_analysis?: HistoricalAnalysisStateShape;
  artifacts?: ArtifactRecordShape[];
  open_questions?: OpenQuestionRecordShape[];
}

// Top-level snapshot shape
export interface WorkflowSnapshotShape {
  schema_version: number;
  workflow_id: string;
  workspace_dir: string;
  arch_repo_dir: string;
  engine_name: string;
  timeout_seconds: number;
  updated_at: string;
  session: WorkflowSessionShape;
}

/**
 * Parse a YAML string containing a WorkflowSnapshot into a typed object.
 * The YAML content is expected to match the structure produced by the
 * Python backend (via WorkflowSnapshot.model_dump(mode="json") and yaml.safe_dump).
 *
 * @param yamlText - The YAML string to parse
 * @returns A typed WorkflowSnapshotShape object
 * @throws Error if the YAML does not parse to an object or is malformed
 */
export function parseSnapshotYaml(yamlText: string): WorkflowSnapshotShape {
  const parsed = yaml.load(yamlText);
  if (typeof parsed !== "object" || parsed === null) {
    throw new Error(
      `snapshot YAML did not parse to an object: ${yamlText.slice(0, 200)}`
    );
  }
  return parsed as WorkflowSnapshotShape;
}
