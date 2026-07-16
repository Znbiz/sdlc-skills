import type { ConversationItemResponse } from "../../shared/api/models";
import { formatDateTime } from "../../shared/format/format";
import styles from "./timeline.module.css";

export function Timeline({ items }: { items: ConversationItemResponse[] }) {
  if (items.length === 0) {
    return <p className={styles.empty}>Пока нет событий conversation.</p>;
  }

  return (
    <ol className={styles.list}>
      {items.map((item) => (
        <li key={item.item_id} className={styles.item}>
          <div className={styles.itemHeader}>
            <span className={styles.kind}>{item.item_kind}</span>
            <span className={styles.time}>{formatDateTime(item.created_at)}</span>
          </div>
          {item.step_id && <span className={styles.step}>{item.step_id}</span>}
          <span className={styles.actor}>{item.actor}</span>
        </li>
      ))}
    </ol>
  );
}
