import type { PropsWithChildren, ReactNode } from "react";
import styles from "./card.module.css";

export function Card({ title, actions, children }: PropsWithChildren<{ title?: ReactNode; actions?: ReactNode }>) {
  return (
    <section className={styles.card}>
      {(title || actions) && (
        <header className={styles.header}>
          {title && <h3 className={styles.title}>{title}</h3>}
          {actions && <div className={styles.actions}>{actions}</div>}
        </header>
      )}
      <div className={styles.body}>{children}</div>
    </section>
  );
}
