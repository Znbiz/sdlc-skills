import { useState } from "react";
import type { FormEvent } from "react";
import { Button } from "../../shared/ui/button";
import type { CliEngine, InitArchInput, PreviousInitInputResponse } from "../../shared/api/models";
import styles from "./init-arch-form.module.css";

const DEFAULT_WORKSPACE_DIR = "/workspace";
const DEFAULT_TIMEOUT_SECONDS = 900;
const ANALYSIS_SCOPE_CONSTANT = "full";

interface FormState {
  productName: string;
  repoList: string[];
  engineName: CliEngine;
  timeoutSeconds: string;
  workspaceDir: string;
  archRepoDir: string;
}

const INITIAL_STATE: FormState = {
  productName: "",
  repoList: [""],
  engineName: "claude",
  timeoutSeconds: String(DEFAULT_TIMEOUT_SECONDS),
  workspaceDir: DEFAULT_WORKSPACE_DIR,
  archRepoDir: "",
};

function initialStateFrom(previousInput: PreviousInitInputResponse | null | undefined): FormState {
  if (!previousInput) return INITIAL_STATE;
  return {
    productName: previousInput.product_name,
    repoList: previousInput.repo_list.length > 0 ? previousInput.repo_list : [""],
    engineName: INITIAL_STATE.engineName,
    timeoutSeconds: INITIAL_STATE.timeoutSeconds,
    workspaceDir: previousInput.workspace_dir || DEFAULT_WORKSPACE_DIR,
    archRepoDir: previousInput.arch_repo_dir,
  };
}

function validate(state: FormState): string | null {
  if (!state.productName.trim()) return "Укажите название продукта.";
  if (!state.repoList.some((entry) => entry.trim())) return "Добавьте хотя бы один репозиторий.";
  const timeoutSeconds = Number(state.timeoutSeconds);
  if (!Number.isInteger(timeoutSeconds) || timeoutSeconds <= 0) return "Таймаут шага должен быть целым числом больше нуля.";
  if (!state.workspaceDir.trim()) return "Workspace dir не может быть пустым.";
  return null;
}

function buildInput(state: FormState): InitArchInput {
  return {
    product_name: state.productName.trim(),
    analysis_scope: ANALYSIS_SCOPE_CONSTANT,
    workspace_dir: state.workspaceDir.trim(),
    arch_repo_dir: state.archRepoDir.trim(),
    repo_list: state.repoList.map((entry) => entry.trim()).filter((entry) => entry.length > 0),
    engine_name: state.engineName,
    timeout_seconds: Number(state.timeoutSeconds),
  };
}

export function InitArchForm({
  onSubmit,
  isSubmitting,
  previousInput,
}: {
  onSubmit: (input: InitArchInput) => void;
  isSubmitting: boolean;
  previousInput?: PreviousInitInputResponse | null;
}) {
  const [state, setState] = useState<FormState>(() => initialStateFrom(previousInput));
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  const updateRepo = (index: number, value: string) => {
    setState((prev) => ({ ...prev, repoList: prev.repoList.map((entry, entryIndex) => (entryIndex === index ? value : entry)) }));
  };

  const addRepo = () => setState((prev) => ({ ...prev, repoList: [...prev.repoList, ""] }));

  const removeRepo = (index: number) =>
    setState((prev) => ({ ...prev, repoList: prev.repoList.length > 1 ? prev.repoList.filter((_, entryIndex) => entryIndex !== index) : prev.repoList }));

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const error = validate(state);
    setValidationError(error);
    if (error) return;
    onSubmit(buildInput(state));
  };

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <label>
        Название продукта
        <input
          value={state.productName}
          onChange={(event) => setState((prev) => ({ ...prev, productName: event.target.value }))}
          placeholder="Arch Docs Gateway"
        />
      </label>

      <fieldset className={styles.repoList}>
        <legend>Репозитории</legend>
        {state.repoList.map((repo, index) => (
          <div key={index} className={styles.repoRow}>
            <input value={repo} onChange={(event) => updateRepo(index, event.target.value)} placeholder="https://github.com/org/repo.git" />
            <Button type="button" variant="danger" onClick={() => removeRepo(index)} disabled={state.repoList.length === 1}>
              Убрать
            </Button>
          </div>
        ))}
        <Button type="button" variant="secondary" onClick={addRepo}>
          Добавить репозиторий
        </Button>
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
