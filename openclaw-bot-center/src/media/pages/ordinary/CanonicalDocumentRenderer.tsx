import { Fragment, type ReactNode } from "react";
import { FileText } from "lucide-react";
import type {
  DocumentBlock,
  DocumentInlineNode,
  DocumentListBlock,
  DocumentValue,
} from "../../documentWorkflow";
import styles from "./CanonicalDocumentRenderer.module.css";

export default function CanonicalDocumentRenderer({ blocks }: { blocks: DocumentBlock[] }) {
  return <div className={styles.documentBody}>{blocks.map((block) => <DocumentBlockView block={block} key={block.id} />)}</div>;
}

function DocumentBlockView({ block }: { block: DocumentBlock }) {
  return <div data-block-id={block.id} data-block-type={block.type}>{renderDocumentBlock(block)}</div>;
}

function renderDocumentBlock(block: DocumentBlock): ReactNode {
  switch (block.type) {
    case "paragraph":
      return <p className={styles.richText}>{renderInlineRuns(block.content)}</p>;
    case "quote":
      return <blockquote className={styles.quote}><p className={styles.richText}>{renderInlineRuns(block.content)}</p></blockquote>;
    case "heading_1": return <h1 className={styles.documentHeading}>{renderInlineRuns(block.content)}</h1>;
    case "heading_2": return <h2 className={styles.documentHeading}>{renderInlineRuns(block.content)}</h2>;
    case "heading_3": return <h3 className={styles.documentHeading}>{renderInlineRuns(block.content)}</h3>;
    case "heading_4": return <h4 className={styles.documentHeading}>{renderInlineRuns(block.content)}</h4>;
    case "heading_5": return <h5 className={styles.documentHeading}>{renderInlineRuns(block.content)}</h5>;
    case "heading_6": return <h6 className={styles.documentHeading}>{renderInlineRuns(block.content)}</h6>;
    case "heading_7": return <div className={styles.documentHeading} role="heading" aria-level={7}>{renderInlineRuns(block.content)}</div>;
    case "heading_8": return <div className={styles.documentHeading} role="heading" aria-level={8}>{renderInlineRuns(block.content)}</div>;
    case "heading_9": return <div className={styles.documentHeading} role="heading" aria-level={9}>{renderInlineRuns(block.content)}</div>;
    case "bullet_list":
    case "ordered_list":
      return renderList(block);
    case "todo_item":
      return <label className={styles.todo}><input type="checkbox" checked={block.attrs.checked} readOnly /><span className={block.attrs.checked ? styles.todoChecked : ""}>{renderInlineRuns(block.content)}</span></label>;
    case "code_block":
      return <div className={styles.codeWrap}><span className={styles.codeLanguage}>{block.attrs.language ?? "纯文本"}</span><pre className={styles.codeBlock} data-language={block.attrs.language ?? undefined}><code>{block.text}</code></pre></div>;
    case "divider":
      return <hr className={styles.divider} />;
    case "callout":
      return <aside className={styles.callout} data-tone={block.attrs.semanticTone}><strong>{calloutLabel(block.attrs.semanticTone)}</strong><p className={styles.richText}>{renderInlineRuns(block.content)}</p></aside>;
    case "table": {
      const headerRows = block.rows.slice(0, block.attrs.headerRowCount);
      const bodyRows = block.rows.slice(block.attrs.headerRowCount);
      const renderRow = (row: (typeof block.rows)[number], header: boolean) => <tr key={row.id}>{row.cells.map((cell) => header ? <th key={cell.id} scope="col">{renderInlineRuns(cell.content)}</th> : <td key={cell.id}>{renderInlineRuns(cell.content)}</td>)}</tr>;
      return <div className={styles.tableWrap}><table className={styles.documentTable}>{headerRows.length ? <thead>{headerRows.map((row) => renderRow(row, true))}</thead> : null}<tbody>{bodyRows.map((row) => renderRow(row, false))}</tbody></table></div>;
    }
    case "image": {
      const src = documentResourceHref(block.attrs.publicResourceId);
      return <figure className={styles.imageFigure} data-public-resource-id={block.attrs.publicResourceId} data-content-checksum={block.attrs.contentChecksum}>{src ? <img className={styles.documentImage} src={src} alt={block.attrs.altText} width={block.attrs.width} height={block.attrs.height} loading="lazy" data-public-resource-id={block.attrs.publicResourceId} data-content-checksum={block.attrs.contentChecksum} /> : <div className={styles.resourcePlaceholder} data-public-resource-id={block.attrs.publicResourceId} data-content-checksum={block.attrs.contentChecksum}>图片暂不可读取</div>}<figcaption><span>{block.attrs.altText || "图片"}</span><small>{block.attrs.width} x {block.attrs.height}</small></figcaption></figure>;
    }
    case "attachment": {
      const href = documentResourceHref(block.attrs.publicResourceId);
      return <div className={styles.attachment} data-public-resource-id={block.attrs.publicResourceId} data-content-checksum={block.attrs.contentChecksum}><FileText size={17} aria-hidden="true" /><div><strong>{block.attrs.fileName}</strong><span>{resourceTypeLabel(block.attrs.contentType)}</span></div>{href ? <a href={href} target="_blank" rel="noreferrer" data-public-resource-id={block.attrs.publicResourceId} data-content-checksum={block.attrs.contentChecksum}>打开附件</a> : null}</div>;
    }
    case "data_snapshot":
      return <aside className={styles.snapshot} data-protected="true"><strong>受保护数据快照</strong><dl>{Object.entries(block.attrs.displayFields).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{formatSnapshotValue(value)}</dd></div>)}</dl><small>{block.attrs.semanticPurpose} · 对象 {block.attrs.publicObjectId} · 来源修订 {block.attrs.sourceRevision} · {formatTimestamp(block.attrs.capturedAt)}</small></aside>;
  }
}

function renderList(block: DocumentListBlock): ReactNode {
  const List = block.type === "ordered_list" ? "ol" : "ul";
  return <List className={styles.documentList}>{block.items.map((item) => <li key={item.id}><span className={styles.richText}>{renderInlineRuns(item.content)}</span>{item.children.length ? <div className={styles.nestedList}>{item.children.map((child) => <Fragment key={child.id}>{renderList(child)}</Fragment>)}</div> : null}</li>)}</List>;
}

function renderInlineRuns(runs: DocumentInlineNode[]): ReactNode[] {
  return runs.map((run, index) => {
    let node: ReactNode = run.text;
    for (const mark of run.marks) {
      if (mark === "bold") node = <strong>{node}</strong>;
      else if (mark === "italic") node = <em>{node}</em>;
      else if (mark === "underline") node = <u>{node}</u>;
      else if (mark === "strike") node = <s>{node}</s>;
      else if (mark === "inline_code") node = <code className={styles.inlineCode}>{node}</code>;
      else if (typeof mark === "object" && mark.type === "link") {
        const href = resourceHref(mark.href);
        node = href ? <a href={href} title={mark.title ?? undefined} target="_blank" rel="noreferrer">{node}</a> : <span className={styles.invalidLink}>{node}</span>;
      }
    }
    return <Fragment key={`${index}-${run.text.slice(0, 12)}`}>{node}</Fragment>;
  });
}

function resourceHref(value: string): string | undefined {
  return /^(?:https?:|mailto:|data:image\/|blob:|\/)/i.test(value) ? value : undefined;
}

function documentResourceHref(value: string): string | undefined {
  return /^[A-Za-z0-9_-]{8,160}$/.test(value)
    ? `/openclaw/media/api/document-resources/${encodeURIComponent(value)}`
    : undefined;
}

function resourceTypeLabel(contentType: string): string {
  if (contentType === "application/pdf") return "PDF 文档";
  if (contentType.startsWith("image/")) return "图片";
  if (contentType === "text/plain") return "文本文件";
  return "附件";
}

function calloutLabel(tone: "info" | "success" | "warning" | "danger"): string {
  return { info: "提示", success: "成功", warning: "注意", danger: "风险" }[tone];
}

function formatSnapshotValue(value: DocumentValue): string {
  if (Array.isArray(value)) return value.map((item) => String(item)).join("、");
  if (value === null) return "未提供";
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}
