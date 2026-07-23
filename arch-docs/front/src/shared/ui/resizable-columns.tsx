import { useRef, useState, type ReactNode } from "react";
import styles from "./resizable-columns.module.css";

const MIN_SIDE_WIDTH_PX = 220;
const MIN_MIDDLE_WIDTH_PX = 280;

export function ResizableColumns({
  columns,
  defaultWidths,
  onWidthsCommit,
}: {
  columns: [ReactNode, ReactNode, ReactNode];
  defaultWidths: [left: number, right: number];
  onWidthsCommit?: (widths: [left: number, right: number]) => void;
}) {
  const [leftWidth, setLeftWidth] = useState(defaultWidths[0]);
  const [rightWidth, setRightWidth] = useState(defaultWidths[1]);
  const containerRef = useRef<HTMLDivElement>(null);
  // во время драга mousemove сыпется чаще, чем React успевает закоммитить render - держим
  // "живые" значения в ref, чтобы mouseup отправил в onWidthsCommit именно последнее значение
  const liveLeftRef = useRef(leftWidth);
  const liveRightRef = useRef(rightWidth);

  const startDrag = (edge: "left" | "right") => (downEvent: React.MouseEvent) => {
    downEvent.preventDefault();
    const container = containerRef.current;
    if (!container) return;
    const containerWidth = container.getBoundingClientRect().width;
    const startX = downEvent.clientX;
    const startLeft = liveLeftRef.current;
    const startRight = liveRightRef.current;
    const maxSideWidth = Math.max(containerWidth - MIN_MIDDLE_WIDTH_PX - MIN_SIDE_WIDTH_PX, MIN_SIDE_WIDTH_PX);

    const onMouseMove = (moveEvent: MouseEvent) => {
      const delta = moveEvent.clientX - startX;
      if (edge === "left") {
        const next = Math.min(Math.max(startLeft + delta, MIN_SIDE_WIDTH_PX), maxSideWidth);
        liveLeftRef.current = next;
        setLeftWidth(next);
      } else {
        const next = Math.min(Math.max(startRight - delta, MIN_SIDE_WIDTH_PX), maxSideWidth);
        liveRightRef.current = next;
        setRightWidth(next);
      }
    };

    const onMouseUp = () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
      onWidthsCommit?.([liveLeftRef.current, liveRightRef.current]);
    };

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  };

  return (
    <div ref={containerRef} className={styles.container}>
      <div className={styles.column} style={{ width: leftWidth, flexShrink: 0 }}>
        {columns[0]}
      </div>
      <div
        className={styles.divider}
        role="separator"
        aria-label="Изменить ширину левой колонки"
        onMouseDown={startDrag("left")}
      />
      <div className={styles.column} style={{ flex: 1, minWidth: MIN_MIDDLE_WIDTH_PX }}>
        {columns[1]}
      </div>
      <div
        className={styles.divider}
        role="separator"
        aria-label="Изменить ширину правой колонки"
        onMouseDown={startDrag("right")}
      />
      <div className={styles.column} style={{ width: rightWidth, flexShrink: 0 }}>
        {columns[2]}
      </div>
    </div>
  );
}
