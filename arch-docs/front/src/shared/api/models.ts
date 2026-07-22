export type CliEngine = "codex" | "claude";

export interface CliEngineAuthInfo {
  authenticated: boolean;
  auth_status: string;
  auth_file_exists: boolean;
}

export interface CliAuthStatusResponse {
  codex: CliEngineAuthInfo;
  claude: CliEngineAuthInfo;
}

export type AuthFlowStatus = "pending" | "success" | "failed" | "expired";

export interface AuthSessionResponse {
  auth_session_id: string;
  cli_engine: CliEngine;
  auth_flow_status: AuthFlowStatus;
  instructions: string | null;
  verification_uri: string | null;
  user_code: string | null;
}

export interface InitAuthResponse {
  auth_session_id: string;
  cli_engine: CliEngine;
  auth_flow_status: AuthFlowStatus;
  instructions: string | null;
  verification_uri: string | null;
  user_code: string | null;
  expires_at: string;
}

export interface GitCredentialsStatusResponse {
  configured: boolean;
  configured_hosts: string[];
}

export interface CheckGitAccessResponse {
  repository_url: string;
  accessible: boolean;
  access_status: string;
  reason_code: string | null;
  message: string;
}

// action_type здесь всегда равен backend-овскому interrupt_type. Известные значения:
// "user_question", "user_input", "temporal_window_confirmation", "step_failed".
export interface RequiredActionResponse {
  action_type: string;
  question_id: string | null;
  action_status: string;
  payload: Record<string, unknown>;
}

export interface InitArchInput {
  product_name: string;
  analysis_scope: string;
  workspace_dir: string;
  arch_repo_dir: string;
  repo_list: string[];
  engine_name: CliEngine;
  timeout_seconds: number;
}

export interface ResponseStatusResponse {
  response_id: string;
  conversation_id: string;
  workflow_type: string;
  response_status: string;
  current_step_id: string;
  current_repo_name: string;
  workspace_dir: string;
  arch_repo_dir: string;
  completed_steps: string[];
  required_actions: RequiredActionResponse[];
  created_at: string;
  updated_at: string;
  error_message: string | null;
  terminal_result: Record<string, unknown> | null;
}

export interface PreviousInitInputResponse {
  product_name: string;
  analysis_scope: string;
  workspace_dir: string;
  arch_repo_dir: string;
  repo_list: string[];
}

export interface ConversationResponse {
  conversation_id: string;
  created_at: string;
  updated_at: string;
  active_response: ResponseStatusResponse | null;
  previous_init_input: PreviousInitInputResponse | null;
}

export interface ConversationItemResponse {
  item_id: string;
  item_kind: string;
  actor: string;
  step_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface ConversationItemsResponse {
  conversation_id: string;
  items: ConversationItemResponse[];
}

export type DocsNodeType = "directory" | "file";
export type DocsMediaKind = "markdown" | "yaml" | "json" | "text" | "unsupported";

export interface DocsTreeNode {
  path: string;
  name: string;
  node_type: DocsNodeType;
  children: DocsTreeNode[] | null;
  size: number;
  modified_at: string;
  media_kind: DocsMediaKind | null;
}

export interface DocsFileResponse {
  path: string;
  name: string;
  media_kind: DocsMediaKind;
  content: string | null;
  encoding: string | null;
  size: number;
  modified_at: string;
}
