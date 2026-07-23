import { useState } from "react";
import type { ConversationItemResponse } from "../../shared/api/models";
import { formatDateTime } from "../../shared/format/format";
import styles from "./timeline.module.css";

function formatPayloadValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

export function Timeline({ items }: { items: ConversationItemResponse[] }) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  if (items.length === 0) {
    return <p className={styles.empty}>Пока нет событий conversation.</p>;
  }

  const toggle = (itemId: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  };

  // Backend отдаёт по возрастанию created_at - в таймлайне удобнее видеть самые свежие события сверху.
  const orderedItems = [...items].reverse();

  return (
    <ol className={styles.list}>
      {orderedItems.map((item) => {
        const payloadEntries = Object.entries(item.payload);
        const hasDetails = payloadEntries.length > 0;
        const isExpanded = expandedIds.has(item.item_id);
        return (
          <li key={item.item_id} className={styles.item}>
            <button
              type="button"
              className={styles.itemButton}
              disabled={!hasDetails}
              aria-expanded={hasDetails ? isExpanded : undefined}
              onClick={() => toggle(item.item_id)}
            >
              <div className={styles.itemHeader}>
                <span className={styles.kind}>
                  {hasDetails && <span className={styles.disclosure}>{isExpanded ? "▾" : "▸"}</span>}
                  {item.item_kind}
                </span>
                <span className={styles.time}>{formatDateTime(item.created_at)}</span>
              </div>
              {item.step_id && <span className={styles.step}>{item.step_id}</span>}
              <span className={styles.actor}>{item.actor}</span>
            </button>
            {hasDetails && isExpanded && (
              <dl className={styles.details}>
                {payloadEntries.map(([key, value]) => (
                  <div key={key} className={styles.detailRow}>
                    <dt className={styles.detailKey}>{key}</dt>
                    <dd className={styles.detailValue}>{formatPayloadValue(value)}</dd>
                  </div>
                ))}
              </dl>
            )}
          </li>
        );
      })}
    </ol>
  );
}
