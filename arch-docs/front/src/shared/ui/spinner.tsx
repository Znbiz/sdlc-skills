import styles from "./spinner.module.css";

export function Spinner({ label }: { label?: string }) {
  return (
    <div className={styles.wrapper} role="status" aria-live="polite">
      <span className={styles.spinner} aria-hidden="true" />
      <span>{label ?? "Загрузка…"}</span>
    </div>
  );
}
