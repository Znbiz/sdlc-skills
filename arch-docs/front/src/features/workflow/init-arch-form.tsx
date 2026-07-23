import { useState } from "react";
import type { FormEvent } from "react";
import { Button } from "../../shared/ui/button";
import type { CliEngine, InitArchInput, PreviousInitInputResponse } from "../../shared/api/models";
import styles from "./init-arch-form.module.css";

const DEFAULT_TIMEOUT_SECONDS = 900;
const ANALYSIS_SCOPE_CONSTANT = "full";

interface FormState {
  engineName: CliEngine;
  timeoutSeconds: string;
  workspaceDir: string;
  archRepoDir: string;
}

function defaultState(defaultWorkspaceDir: string): FormState {
  return {
    engineName: "claude",
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
    engineName: "claude",
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
  return null;
}

function buildInput(state: FormState, productName: string): InitArchInput {
  return {
    product_name: productName,
    analysis_scope: ANALYSIS_SCOPE_CONSTANT,
    workspace_dir: state.workspaceDir.trim(),
    arch_repo_dir: state.archRepoDir.trim(),
    engine_name: state.engineName,
    timeout_seconds: Number(state.timeoutSeconds),
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
        <select value={state.engineName} onChange={(event) => setState((prev) => ({ ...prev, engineName: event.target.value as CliEngine }))}>
          <option value="claude">claude</option>
          <option value="codex">codex</option>
        </select>
      </label>

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
