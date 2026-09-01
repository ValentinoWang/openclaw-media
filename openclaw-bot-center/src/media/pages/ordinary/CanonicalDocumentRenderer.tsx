import { Fragment, type ReactNode } from "react";
import { FileImage, FileText } from "lucide-react";
import type {
  DocumentBlock,
  DocumentDataSnapshotBlock,
  DocumentInlineNode,
  DocumentListBlock,
  DocumentTableBlock,
  DocumentValue,
} from "../../documentWorkflow";
import { isPublicId } from "../../identifiers";
import { ECHO_INVALID, formatDateTime } from "../../ui/datetime";
import styles from "./CanonicalDocumentRenderer.module.css";

type DocumentSemanticPurpose =
  | DocumentTableBlock["attrs"]["semanticPurpose"]
  | DocumentDataSnapshotBlock["attrs"]["semanticPurpose"];

const DOCUMENT_BLOCK_LABELS: Record<DocumentBlock["type"], string> = {
  paragraph: "段落",
  quote: "引用",
  heading_1: "一级标题",
  heading_2: "二级标题",
  heading_3: "三级标题",
  heading_4: "四级标题",
  heading_5: "五级标题",
  heading_6: "六级标题",
  heading_7: "七级标题",
  heading_8: "八级标题",
  heading_9: "九级标题",
  bullet_list: "无序列表",
  ordered_list: "有序列表",
  todo_item: "待办事项",
  code_block: "代码块",
  divider: "分隔线",
  callout: "提示块",
  image: "图片",
  attachment: "附件",
  table: "表格",
  data_snapshot: "数据快照",
};

const DOCUMENT_SEMANTIC_PURPOSE_LABELS: Record<DocumentSemanticPurpose, string> = {
  general: "通用表格",
  storyboard: "分镜表",
  publishing_checklist: "发布清单",
  metric_snapshot: "指标快照",
  evidence_index: "证据索引",
};

const DOCUMENT_WIRE_VALUE_LABELS: Record<string, string> = {
  ...DOCUMENT_BLOCK_LABELS,
  ...DOCUMENT_SEMANTIC_PURPOSE_LABELS,
  internal: "网页端",
  lark: "飞书",
  personal_web: "个人工作区",
  organization_lark: "组织工作区",
  draft: "草稿",
  generating: "正在生成",
  ready: "可用",
  failed: "处理失败",
  conflict: "需要处理冲突",
  archived: "已归档",
  queued: "排队中",
  rendering: "正在处理",
  succeeded: "已完成",
  running: "处理中",
  pending: "等待处理",
  unknown: "待对账",
  stale: "待回读",
  partial: "部分完成",
  unavailable: "不可用",
  docx: "Word 文档",
  pdf: "PDF 文档",
  info: "提示",
  success: "成功",
  warning: "注意",
  danger: "风险",
  bold: "加粗",
  italic: "斜体",
  underline: "下划线",
  strike: "删除线",
  inline_code: "行内代码",
  link: "链接",
  read: "回读",
  write: "写入",
  owner: "组织负责人",
  member: "组织成员",
  unsupported: "结构不支持",
  empty: "暂无数据",
  "application/pdf": "PDF 文档",
  "text/plain": "文本文件",
};

const SNAPSHOT_FIELD_LABELS: Record<string, string> = {
  sample_count: "实测样本",
  water_loss_rate: "失水率",
  post_application_water_loss_rate: "涂抹后失水率",
  test_duration: "测试时长",
  test_duration_days: "测试时长",
  environment_humidity: "环境湿度",
  humidity_percent: "环境湿度",
  cooperation_amount: "合作金额",
  schedule_days: "排期天数",
  delivery_count: "交付条数",
  public_object_id: "对象",
  publicObjectId: "对象",
  source_revision: "来源修订",
  sourceRevision: "来源修订",
  captured_at: "采集时间",
  capturedAt: "采集时间",
  semantic_purpose: "数据用途",
  semanticPurpose: "数据用途",
  body_authority: "正文权威",
  bodyAuthority: "正文权威",
  workspace_mode: "工作区",
  workspaceMode: "工作区",
  revision_state: "修订状态",
  revisionState: "修订状态",
  export_state: "导出状态",
  exportState: "导出状态",
  content_type: "内容类型",
  contentType: "内容类型",
};

const SNAPSHOT_ENUM_FIELDS = new Set([
  "authority",
  "body_authority",
  "bodyAuthority",
  "workspace_mode",
  "workspaceMode",
  "state",
  "status",
  "revision_state",
  "revisionState",
  "export_state",
  "exportState",
  "semantic_purpose",
  "semanticPurpose",
  "block_type",
  "blockType",
  "type",
  "kind",
  "tone",
  "semantic_tone",
  "semanticTone",
  "format",
  "export_format",
  "exportFormat",
  "operation",
  "sync_status",
  "syncStatus",
]);

export default function CanonicalDocumentRenderer({ blocks, highlightedBlockIds = [] }: { blocks: DocumentBlock[]; highlightedBlockIds?: readonly string[] }) {
  const highlighted = new Set(highlightedBlockIds);
  return <div className={styles.documentBody}>{blocks.map((block) => <DocumentBlockView block={block} highlighted={highlighted.has(block.id)} key={block.id} />)}</div>;
}

function DocumentBlockView({ block, highlighted }: { block: DocumentBlock; highlighted: boolean }) {
  return <div data-block-id={block.id} data-block-type={block.type} data-document-state={highlighted ? "unsupported" : undefined}>{highlighted ? <span className={styles.blockFlag}>需要处理</span> : null}{renderDocumentBlock(block)}</div>;
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
      return <div className={styles.codeWrap}><span className={styles.codeLanguage}>{codeLanguageLabel(block.attrs.language)}</span><pre className={styles.codeBlock} data-language={block.attrs.language ?? undefined}><code>{block.text}</code></pre></div>;
    case "divider":
      return <hr className={styles.divider} />;
    case "callout": {
      const tone = sharedTone(block.attrs.semanticTone);
      return <aside className={`${styles.callout} mg-panel`} data-component="mg-panel" data-tone={tone}><span className="mg-badge" data-component="mg-badge" data-tone={tone}>{calloutLabel(block.attrs.semanticTone)}</span><p className={styles.richText}>{renderInlineRuns(block.content)}</p></aside>;
    }
    case "table": {
      const headerRows = block.rows.slice(0, block.attrs.headerRowCount);
      const bodyRows = block.rows.slice(block.attrs.headerRowCount);
      const renderRow = (row: (typeof block.rows)[number], header: boolean) => <tr key={row.id}>{row.cells.map((cell) => header ? <th key={cell.id} scope="col">{renderInlineRuns(cell.content)}</th> : <td key={cell.id}>{renderInlineRuns(cell.content)}</td>)}</tr>;
      return <div className={`${styles.tableWrap} mg-panel`} data-component="mg-panel"><table className={styles.documentTable}>{headerRows.length ? <thead>{headerRows.map((row) => renderRow(row, true))}</thead> : null}<tbody>{bodyRows.map((row) => renderRow(row, false))}</tbody></table></div>;
    }
    case "image": {
      const src = documentResourceHref(block.attrs.publicResourceId);
      return <figure className={styles.imageFigure} data-public-resource-id={block.attrs.publicResourceId} data-content-checksum={block.attrs.contentChecksum}>{src ? <img className={styles.documentImage} src={src} alt={block.attrs.altText} width={block.attrs.width} height={block.attrs.height} loading="lazy" data-public-resource-id={block.attrs.publicResourceId} data-content-checksum={block.attrs.contentChecksum} /> : <div className={`${styles.resourcePlaceholder} mg-state`} data-component="mg-state" data-state="empty" data-tone="warn" role="status" data-public-resource-id={block.attrs.publicResourceId} data-content-checksum={block.attrs.contentChecksum}><span className="mg-state-art" data-state-art="empty" aria-hidden="true"><FileImage size={18} /></span><span>图片暂不可读取</span></div>}<figcaption><span>{block.attrs.altText || "图片"}</span><small>{block.attrs.width} x {block.attrs.height}</small></figcaption></figure>;
    }
    case "attachment": {
      const href = documentResourceHref(block.attrs.publicResourceId);
      return <div className={`${styles.attachment} mg-panel`} data-component="mg-panel" data-accent="studio" data-public-resource-id={block.attrs.publicResourceId} data-content-checksum={block.attrs.contentChecksum}><FileText size={17} aria-hidden="true" /><div><strong>{block.attrs.fileName}</strong><span>{resourceTypeLabel(block.attrs.contentType)}</span></div>{href ? <a href={href} target="_blank" rel="noreferrer" data-public-resource-id={block.attrs.publicResourceId} data-content-checksum={block.attrs.contentChecksum}>打开附件</a> : null}</div>;
    }
    case "data_snapshot":
      return <aside className={`${styles.snapshot} mg-panel`} data-component="mg-panel" data-accent="archive" data-protected="true"><span className="mg-badge" data-component="mg-badge" data-tone="info">受保护数据快照</span><dl>{Object.entries(block.attrs.displayFields).map(([key, value]) => <div key={key}><dt>{snapshotFieldLabel(key)}</dt><dd>{formatSnapshotValue(key, value)}</dd></div>)}</dl><small>{semanticPurposeLabel(block.attrs.semanticPurpose)} · 对象 {block.attrs.publicObjectId} · 来源修订 {block.attrs.sourceRevision} · {formatTimestamp(block.attrs.capturedAt)}</small></aside>;
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
  return isPublicId(value)
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

function sharedTone(tone: "info" | "success" | "warning" | "danger"): "info" | "good" | "warn" | "danger" {
  const tones: Record<typeof tone, "info" | "good" | "warn" | "danger"> = {
    info: "info",
    success: "good",
    warning: "warn",
    danger: "danger",
  };
  return tones[tone];
}

function semanticPurposeLabel(value: DocumentSemanticPurpose): string {
  return DOCUMENT_SEMANTIC_PURPOSE_LABELS[value] ?? "数据用途待确认";
}

function codeLanguageLabel(value: string | null): string {
  if (value === null) return "纯文本";
  return DOCUMENT_WIRE_VALUE_LABELS[value]
    ?? (isSnakeCaseIdentifier(value) ? "代码语言待确认" : value);
}

function snapshotFieldLabel(value: string): string {
  const label = SNAPSHOT_FIELD_LABELS[value] ?? DOCUMENT_WIRE_VALUE_LABELS[value];
  return label ?? "数据项";
}

function formatSnapshotValue(fieldName: string, value: DocumentValue): string {
  if (Array.isArray(value)) return value.map((item) => formatSnapshotScalar(fieldName, item)).join("、");
  if (value === null) return "未提供";
  if (typeof value === "boolean") return value ? "是" : "否";
  return formatSnapshotScalar(fieldName, value);
}

function formatSnapshotScalar(fieldName: string, value: string | number | boolean): string {
  if (typeof value !== "string") return String(value);
  return DOCUMENT_WIRE_VALUE_LABELS[value]
    ?? (SNAPSHOT_ENUM_FIELDS.has(fieldName) || isSnakeCaseIdentifier(value) ? "待确认" : value);
}

function isSnakeCaseIdentifier(value: string): boolean {
  return /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/u.test(value);
}

function formatTimestamp(value: string): string {
  return formatDateTime(value, { empty: ECHO_INVALID, invalid: ECHO_INVALID });
}
