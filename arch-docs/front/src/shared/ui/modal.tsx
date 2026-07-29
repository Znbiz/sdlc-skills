import type { PropsWithChildren, ReactNode } from "react";
import styles from "./modal.module.css";

export function Modal({
  title,
  onClose,
  children,
  dialogClassName,
}: PropsWithChildren<{ title: ReactNode; onClose: () => void; dialogClassName?: string }>) {
  return (
    <div className={styles.overlay} onClick={onClose}>
      <div
        className={dialogClassName ? `${styles.dialog} ${dialogClassName}` : styles.dialog}
        role="dialog"
        aria-modal="true"
        onClick={(event) => event.stopPropagation()}
      >
        <header className={styles.header}>
          <h3 className={styles.title}>{title}</h3>
          <button type="button" className={styles.closeButton} onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </header>
        <div className={styles.body}>{children}</div>
      </div>
    </div>
  );
}
