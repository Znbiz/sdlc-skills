import { useState } from "react";
import type { DocsTreeNode } from "../../shared/api/models";
import styles from "./file-tree.module.css";

export function ancestorPaths(targetPath: string): Set<string> {
  const segments = targetPath.split("/").filter(Boolean);
  const paths = new Set<string>();
  let current = "";
  for (const segment of segments.slice(0, -1)) {
    current = current ? `${current}/${segment}` : segment;
    paths.add(current);
  }
  return paths;
}

export function FileTree({
  root,
  activePath,
  onSelect,
  onDelete,
}: {
  root: DocsTreeNode;
  activePath: string | null;
  onSelect: (path: string) => void;
  onDelete?: (node: DocsTreeNode) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    const initial = activePath ? ancestorPaths(activePath) : new Set<string>();
    initial.add(root.path);
    return initial;
  });

  const toggle = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  return (
    <ul className={styles.tree} role="tree">
      {(root.children ?? []).map((child) => (
        <TreeNode
          key={child.path}
          node={child}
          depth={0}
          expanded={expanded}
          onToggle={toggle}
          activePath={activePath}
          onSelect={onSelect}
          onDelete={onDelete}
        />
      ))}
    </ul>
  );
}

function TreeNode({
  node,
  depth,
  expanded,
  onToggle,
  activePath,
  onSelect,
  onDelete,
}: {
  node: DocsTreeNode;
  depth: number;
  expanded: Set<string>;
  onToggle: (path: string) => void;
  activePath: string | null;
  onSelect: (path: string) => void;
  onDelete?: (node: DocsTreeNode) => void;
}) {
  const isDirectory = node.node_type === "directory";
  const isOpen = expanded.has(node.path);
  const isActive = node.path === activePath;

  return (
    <li role="treeitem" aria-expanded={isDirectory ? isOpen : undefined}>
      <div className={styles.nodeRow}>
        <button
          type="button"
          className={`${styles.nodeButton} ${isActive ? styles.active : ""}`}
          style={{ paddingLeft: `${depth * 0.9 + 0.4}rem` }}
          onClick={() => (isDirectory ? onToggle(node.path) : onSelect(node.path))}
        >
          {isDirectory ? (isOpen ? "▾" : "▸") : "·"} {node.name}
        </button>
        {onDelete && (
          <button
            type="button"
            className={styles.deleteButton}
            aria-label={`Удалить ${node.name}`}
            title={`Удалить ${node.name}`}
            onClick={(event) => {
              event.stopPropagation();
              onDelete(node);
            }}
          >
            ✕
          </button>
        )}
      </div>
      {isDirectory && isOpen && node.children && (
        <ul className={styles.subtree}>
          {node.children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              onToggle={onToggle}
              activePath={activePath}
              onSelect={onSelect}
              onDelete={onDelete}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
