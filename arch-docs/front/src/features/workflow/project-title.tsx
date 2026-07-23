import { useEffect, useRef, useState } from "react";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { useUpdateProductName } from "./hooks";
import styles from "./project-title.module.css";

export function ProjectTitle({ conversationId, productName }: { conversationId: string; productName: string | null }) {
  const updateProductName = useUpdateProductName(conversationId);
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(productName ?? "");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isEditing) setDraft(productName ?? "");
  }, [productName, isEditing]);

  const displayName = productName?.trim() || conversationId.slice(0, 8);

  const startEditing = () => {
    setDraft(productName ?? "");
    setIsEditing(true);
  };

  const save = () => {
    setIsEditing(false);
    const trimmed = draft.trim();
    if (trimmed === (productName ?? "").trim()) return;
    updateProductName.mutate(trimmed);
  };

  const cancel = () => {
    setDraft(productName ?? "");
    setIsEditing(false);
  };

  if (isEditing) {
    return (
      <div className={styles.editWrapper}>
        <input
          ref={inputRef}
          autoFocus
          className={styles.input}
          value={draft}
          placeholder="Название проекта"
          onChange={(event) => setDraft(event.target.value)}
          onBlur={save}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              inputRef.current?.blur();
            } else if (event.key === "Escape") {
              event.preventDefault();
              cancel();
            }
          }}
        />
        {updateProductName.isError && <ErrorBanner error={updateProductName.error} />}
      </div>
    );
  }

  return (
    <button type="button" className={styles.title} onClick={startEditing} title="Нажмите, чтобы переименовать проект">
      <h1 className={styles.heading}>{displayName}</h1>
      {updateProductName.isPending && <span className={styles.saving}>сохранение…</span>}
    </button>
  );
}
