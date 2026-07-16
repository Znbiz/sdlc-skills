import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import * as YAML from "yaml";
import type { DocsFileResponse } from "../../shared/api/models";
import { formatDateTime, formatFileSize } from "../../shared/format/format";
import styles from "./file-viewer.module.css";

export function FileViewer({ file }: { file: DocsFileResponse }) {
  return (
    <div className={styles.viewer}>
      <div className={styles.meta}>
        <span>{file.path}</span>
        <span>{file.media_kind}</span>
        <span>{formatFileSize(file.size)}</span>
        <span>{formatDateTime(file.modified_at)}</span>
      </div>
      <div className={styles.content}>
        <FileContent file={file} />
      </div>
    </div>
  );
}

function FileContent({ file }: { file: DocsFileResponse }) {
  if (file.content === null) {
    return <p className={styles.unsupported}>Предпросмотр недоступен для этого файла.</p>;
  }

  switch (file.media_kind) {
    case "markdown":
      return (
        <div className={styles.markdown}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{file.content}</ReactMarkdown>
        </div>
      );
    case "yaml":
      return <pre className={styles.code}>{formatYaml(file.content)}</pre>;
    case "json":
      return <pre className={styles.code}>{formatJson(file.content)}</pre>;
    default:
      return <pre className={styles.code}>{file.content}</pre>;
  }
}

function formatYaml(content: string): string {
  try {
    return YAML.stringify(YAML.parse(content));
  } catch {
    return content;
  }
}

function formatJson(content: string): string {
  try {
    return JSON.stringify(JSON.parse(content), null, 2);
  } catch {
    return content;
  }
}
