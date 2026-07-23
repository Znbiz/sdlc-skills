import { useEffect, useRef, useState } from "react";
import { Button } from "../../shared/ui/button";
import { Card } from "../../shared/ui/card";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { Spinner } from "../../shared/ui/spinner";
import type { RepositoryStatusResponse } from "../../shared/api/models";
import {
  useAddConversationRepository,
  useConversationRepositories,
  useRemoveConversationRepository,
  useSubmitResponseAction,
} from "./hooks";
import styles from "./conversation-repositories.module.css";

export interface RunRepositoriesContext {
  responseId: string;
  editable: boolean;
  repositories: RepositoryStatusResponse[];
}

interface DisplayRepository {
  name: string;
  url: string;
  commit: RepositoryStatusResponse | null;
}

function shortCommit(hash: string): string {
  return hash ? hash.slice(0, 8) : "—";
}

function CommitCell({ label, hash, date }: { label: string; hash: string; date: string | null }) {
  return (
    <div className={styles.commitCell}>
      <span className={styles.commitLabel}>{label}</span>
      <span className={styles.commitHash}>{shortCommit(hash)}</span>
      <span className={styles.commitDate}>{date ?? "—"}</span>
    </div>
  );
}

function parseRepositoryEntries(raw: string): string[] {
  const seen = new Set<string>();
  const entries: string[] = [];
  for (const line of raw.split(/\r?\n/)) {
    for (const piece of line.split(",")) {
      const trimmed = piece.trim();
      if (!trimmed || seen.has(trimmed)) continue;
      seen.add(trimmed);
      entries.push(trimmed);
    }
  }
  return entries;
}

function BulkAddRepositoryForm({ conversationId }: { conversationId: string }) {
  const [entries, setEntries] = useState<string[]>([""]);
  const [focusIndex, setFocusIndex] = useState<number | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const addRepository = useAddConversationRepository(conversationId);
  const inputRefs = useRef<Array<HTMLInputElement | null>>([]);

  useEffect(() => {
    if (focusIndex === null) return;
    inputRefs.current[focusIndex]?.focus();
    setFocusIndex(null);
  }, [focusIndex]);

  const updateEntry = (index: number, value: string) => {
    setEntries((prev) => prev.map((entry, i) => (i === index ? value : entry)));
  };

  const removeEntry = (index: number) => {
    setEntries((prev) => (prev.length === 1 ? [""] : prev.filter((_, i) => i !== index)));
  };

  const addEmptyRow = () => {
    setEntries((prev) => [...prev, ""]);
    setFocusIndex(entries.length);
  };

  const handlePaste = (index: number, event: React.ClipboardEvent<HTMLInputElement>) => {
    const pasted = event.clipboardData.getData("text");
    const parsed = parseRepositoryEntries(pasted);
    // одиночное значение - оставляем родное поведение paste в текущее поле
    if (parsed.length <= 1) return;
    event.preventDefault();
    setEntries((prev) => {
      const currentValue = prev[index].trim();
      const merged = currentValue ? [currentValue, ...parsed] : parsed;
      return [...prev.slice(0, index), ...merged, ...prev.slice(index + 1)];
    });
  };

  const handleKeyDown = (index: number, event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void submit();
      return;
    }
    if (event.key === "Enter" && entries[index].trim()) {
      event.preventDefault();
      if (index === entries.length - 1) addEmptyRow();
      else inputRefs.current[index + 1]?.focus();
    }
  };

  const submit = async () => {
    if (entries.every((entry) => !entry.trim())) return;
    setIsSubmitting(true);
    let remaining = entries.filter((entry) => entry.trim());
    let failed = false;
    while (remaining.length > 0) {
      const [next, ...rest] = remaining;
      try {
        // eslint-disable-next-line no-await-in-loop
        await addRepository.mutateAsync(next.trim());
        remaining = rest;
        setEntries(remaining.length > 0 ? remaining : [""]);
      } catch {
        // ошибка уже доступна через addRepository.isError/error; оставляем в списке ещё не
        // добавленные записи (включая упавшую), чтобы пользователь мог поправить и повторить
        failed = true;
        break;
      }
    }
    if (!failed) setEntries([""]);
    setIsSubmitting(false);
  };

  const filledCount = entries.filter((entry) => entry.trim()).length;

  return (
    <div className={styles.addForm}>
      <div className={styles.addRows}>
        {entries.map((entry, index) => (
          // eslint-disable-next-line react/no-array-index-key
          <div key={index} className={styles.addRow}>
            <input
              ref={(el) => {
                inputRefs.current[index] = el;
              }}
              className={styles.addInput}
              placeholder={
                index === 0 && entries.length === 1
                  ? "URL или имя репозитория (можно вставить сразу список)"
                  : "URL или имя репозитория"
              }
              value={entry}
              onChange={(event) => updateEntry(index, event.target.value)}
              onPaste={(event) => handlePaste(index, event)}
              onKeyDown={(event) => handleKeyDown(index, event)}
            />
            {entries.length > 1 && (
              <button
                type="button"
                className={styles.removeRow}
                aria-label="Убрать репозиторий из списка"
                onClick={() => removeEntry(index)}
              >
                ×
              </button>
            )}
          </div>
        ))}
      </div>
      <div className={styles.addActions}>
        <button type="button" className={styles.addRowButton} onClick={addEmptyRow}>
          + ещё репозиторий
        </button>
        <Button variant="primary" disabled={isSubmitting || filledCount === 0} onClick={() => void submit()}>
          {filledCount > 1 ? `Добавить (${filledCount})` : "Добавить"}
        </Button>
      </div>
      {addRepository.isError && <ErrorBanner error={addRepository.error} />}
    </div>
  );
}

function RunAddRepositoryForm({ responseId, conversationId }: { responseId: string; conversationId: string }) {
  const [entry, setEntry] = useState("");
  const submitAction = useSubmitResponseAction(conversationId);

  const submit = () => {
    const trimmed = entry.trim();
    if (!trimmed) return;
    submitAction.mutate(
      { responseId, actionType: "add_repository", value: trimmed },
      { onSuccess: () => setEntry("") },
    );
  };

  return (
    <div className={styles.addForm}>
      <div className={styles.addRow}>
        <input
          className={styles.addInput}
          placeholder="URL или имя репозитория"
          value={entry}
          onChange={(event) => setEntry(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") submit();
          }}
        />
      </div>
      <div className={styles.addActions}>
        <span />
        <Button variant="primary" disabled={submitAction.isPending || !entry.trim()} onClick={submit}>
          Добавить
        </Button>
      </div>
      {submitAction.isError && <ErrorBanner error={submitAction.error} />}
    </div>
  );
}

export function ConversationRepositories({
  conversationId,
  run,
}: {
  conversationId: string;
  run?: RunRepositoriesContext | null;
}) {
  const conversationRepositories = useConversationRepositories(conversationId);
  const removeConversationRepository = useRemoveConversationRepository(conversationId);
  const removeRunRepository = useSubmitResponseAction(conversationId);

  // Список репозиториев проекта - единственный, что показываем: обычно это репозитории проекта
  // (настройка conversation), обогащённые данными коммитов из выбранного прогона, когда они есть.
  // Пока выбранный прогон стоит на паузе/interrupted на шаге клонирования (run.editable), список
  // временно управляется репозиториями САМОГО прогона - это правки "живого" checkpoint'а перед
  // resume (см. add_repository_to_workflow на бэкенде), а не настроек проекта на будущее.
  const useRunAsSource = Boolean(run?.editable);
  const commitByName = new Map((run?.repositories ?? []).map((repository) => [repository.repository_name, repository]));

  const rows: DisplayRepository[] = useRunAsSource
    ? (run!.repositories.map((repository) => ({
        name: repository.repository_name,
        url: repository.repository_url,
        commit: repository,
      })))
    : (conversationRepositories.data ?? []).map((repository) => ({
        name: repository.repository_name,
        url: repository.repository_url,
        commit: commitByName.get(repository.repository_name) ?? null,
      }));

  const removeRow = (name: string) => {
    if (useRunAsSource) {
      removeRunRepository.mutate({ responseId: run!.responseId, actionType: "remove_repository", value: name });
    } else {
      removeConversationRepository.mutate(name);
    }
  };

  const isPending = !useRunAsSource && conversationRepositories.isPending;
  const isError = !useRunAsSource && conversationRepositories.isError;
  const removePending = useRunAsSource ? removeRunRepository.isPending : removeConversationRepository.isPending;
  const removeError = useRunAsSource ? removeRunRepository.error : removeConversationRepository.error;

  return (
    <Card title="Репозитории проекта">
      {isPending && <Spinner label="Загрузка репозиториев…" />}
      {isError && <ErrorBanner error={conversationRepositories.error} onRetry={() => conversationRepositories.refetch()} />}
      {!isPending && !isError && (
        <div className={styles.list}>
          {rows.length === 0 && <p className={styles.empty}>Репозитории ещё не добавлены.</p>}
          {rows.map((repository) => (
            <div key={repository.name} className={styles.row}>
              <div className={styles.info}>
                <span className={styles.name}>{repository.name}</span>
                {repository.url && <span className={styles.url}>{repository.url}</span>}
              </div>
              {repository.commit && (
                <div className={styles.commits}>
                  <CommitCell
                    label="Анализ на коммите"
                    hash={repository.commit.analysis_target_commit}
                    date={repository.commit.analysis_target_commit_date}
                  />
                  <CommitCell
                    label="Последний коммит"
                    hash={repository.commit.remote_head_commit}
                    date={repository.commit.remote_head_commit_date}
                  />
                </div>
              )}
              <Button variant="danger" disabled={removePending} onClick={() => removeRow(repository.name)}>
                Удалить
              </Button>
            </div>
          ))}
        </div>
      )}
      {useRunAsSource ? (
        <RunAddRepositoryForm responseId={run!.responseId} conversationId={conversationId} />
      ) : (
        <BulkAddRepositoryForm conversationId={conversationId} />
      )}
      {removeError && <ErrorBanner error={removeError} />}
    </Card>
  );
}
