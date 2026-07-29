import { useState } from "react";
import type { FormEvent } from "react";
import { Button } from "../../shared/ui/button";
import { useLlmProviderConnections } from "../setup/hooks";
import type { CliEngine, InitArchInput, PreviousInitInputResponse } from "../../shared/api/models";
import styles from "./init-arch-form.module.css";

const DEFAULT_TIMEOUT_SECONDS = 900;
const ANALYSIS_SCOPE_CONSTANT = "full";

// UI-only selection: "external" always runs under codex CLI, wired to a saved
// OpenAI-compatible connection instead of codex's own auth - see
// arch-docs/docs/spec/2026-07-24-external-llm-provider.md, section 6. "langgraph" is a distinct
// fourth engine - a LangGraph tool-calling agent that talks to the same kind of connection
// directly over HTTP, without spawning codex/claude at all - see
// arch-docs/docs/spec/2026-07-25-langgraph-api-agent-runner.md.
type EngineSelection = CliEngine | "external" | "langgraph";

const ENGINES_REQUIRING_PROVIDER_CONNECTION: ReadonlySet<EngineSelection> = new Set(["external", "langgraph"]);

interface FormState {
  engineSelection: EngineSelection;
  providerConnectionId: string | null;
  timeoutSeconds: string;
  workspaceDir: string;
  archRepoDir: string;
}

function defaultState(defaultWorkspaceDir: string): FormState {
  return {
    engineSelection: "claude",
    providerConnectionId: null,
    timeoutSeconds: String(DEFAULT_TIMEOUT_SECONDS),
    workspaceDir: defaultWorkspaceDir,
    archRepoDir: "",
  };
}

function initialStateFrom(
  previousInput: PreviousInitInputResponse | null | undefined,
  defaultWorkspaceDir: string,
): FormState {
  if (!previousInput) return defaultState(defaultWorkspaceDir);
  return {
    engineSelection: "claude",
    providerConnectionId: null,
    timeoutSeconds: String(DEFAULT_TIMEOUT_SECONDS),
    workspaceDir: previousInput.workspace_dir || defaultWorkspaceDir,
    archRepoDir: previousInput.arch_repo_dir,
  };
}

function validate(state: FormState, hasRepositories: boolean): string | null {
  if (!hasRepositories) return "Добавьте хотя бы один репозиторий проекта в колонке слева.";
  const timeoutSeconds = Number(state.timeoutSeconds);
  if (!Number.isInteger(timeoutSeconds) || timeoutSeconds <= 0) return "Таймаут шага должен быть целым числом больше нуля.";
  if (!state.workspaceDir.trim()) return "Workspace dir не может быть пустым.";
  if (ENGINES_REQUIRING_PROVIDER_CONNECTION.has(state.engineSelection) && !state.providerConnectionId) {
    return "Выберите подключение к внешней LLM (или настройте его в Setup).";
  }
  return null;
}

function buildInput(state: FormState, productName: string): InitArchInput {
  const { engineSelection } = state;
  const requiresProviderConnection = ENGINES_REQUIRING_PROVIDER_CONNECTION.has(engineSelection);
  return {
    product_name: productName,
    analysis_scope: ANALYSIS_SCOPE_CONSTANT,
    workspace_dir: state.workspaceDir.trim(),
    arch_repo_dir: state.archRepoDir.trim(),
    engine_name: engineSelection === "external" ? "codex" : engineSelection,
    timeout_seconds: Number(state.timeoutSeconds),
    provider_connection_id: requiresProviderConnection ? state.providerConnectionId : undefined,
  };
}

export function InitArchForm({
  onSubmit,
  isSubmitting,
  previousInput,
  defaultWorkspaceDir,
  productName,
  repositoryNames,
}: {
  onSubmit: (input: InitArchInput) => void;
  isSubmitting: boolean;
  previousInput?: PreviousInitInputResponse | null;
  defaultWorkspaceDir: string;
  productName: string;
  repositoryNames: string[];
}) {
  const [state, setState] = useState<FormState>(() => initialStateFrom(previousInput, defaultWorkspaceDir));
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const llmProviderConnections = useLlmProviderConnections();

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const error = validate(state, repositoryNames.length > 0);
    setValidationError(error);
    if (error) return;
    onSubmit(buildInput(state, productName));
  };

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <p className={styles.productName}>
        Продукт: <strong>{productName}</strong>
      </p>

      <fieldset className={styles.repoList}>
        <legend>Репозитории проекта</legend>
        {repositoryNames.length === 0 ? (
          <p className={styles.validationError}>
            Список репозиториев пуст — добавьте репозитории в колонке слева перед запуском.
          </p>
        ) : (
          <ul>
            {repositoryNames.map((repositoryName) => (
              <li key={repositoryName}>{repositoryName}</li>
            ))}
          </ul>
        )}
      </fieldset>

      <label>
        Движок
        <select
          value={state.engineSelection}
          onChange={(event) =>
            setState((prev) => ({ ...prev, engineSelection: event.target.value as EngineSelection }))
          }
        >
          <option value="claude">Claude Code</option>
          <option value="codex">Codex</option>
          <option value="external">Внешняя LLM (через API-токен)</option>
          <option value="langgraph">LangGraph-агент (прямой API)</option>
        </select>
      </label>

      {ENGINES_REQUIRING_PROVIDER_CONNECTION.has(state.engineSelection) && (
        <label>
          Подключение к внешней LLM
          {llmProviderConnections.data && llmProviderConnections.data.length === 0 ? (
            <p className={styles.validationError}>
              Нет настроенных подключений — добавьте их в Setup перед запуском.
            </p>
          ) : (
            <select
              value={state.providerConnectionId ?? ""}
              onChange={(event) => setState((prev) => ({ ...prev, providerConnectionId: event.target.value || null }))}
            >
              <option value="" disabled>
                Выберите подключение…
              </option>
              {llmProviderConnections.data?.map((connection) => (
                <option key={connection.connection_id} value={connection.connection_id}>
                  {connection.name} ({connection.model})
                </option>
              ))}
            </select>
          )}
        </label>
      )}

      <label>
        Таймаут шага, сек
        <input
          type="number"
          value={state.timeoutSeconds}
          onChange={(event) => setState((prev) => ({ ...prev, timeoutSeconds: event.target.value }))}
        />
      </label>

      <details className={styles.advanced} open={advancedOpen} onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}>
        <summary>Advanced</summary>
        <label>
          Workspace dir
          <input value={state.workspaceDir} onChange={(event) => setState((prev) => ({ ...prev, workspaceDir: event.target.value }))} />
        </label>
        <label>
          Arch repo dir
          <input
            value={state.archRepoDir}
            onChange={(event) => setState((prev) => ({ ...prev, archRepoDir: event.target.value }))}
            placeholder="автоматически внутри workspace_dir, если пусто"
          />
        </label>
      </details>

      {validationError && (
        <p className={styles.validationError} role="alert">
          {validationError}
        </p>
      )}

      <Button type="submit" variant="primary" disabled={isSubmitting}>
        Запустить init_arch
      </Button>
    </form>
  );
}
