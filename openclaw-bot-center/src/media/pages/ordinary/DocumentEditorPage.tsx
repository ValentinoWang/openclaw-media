import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, Link as LinkIcon, RefreshCw, Save, Sparkles, WifiOff, X } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import {
  classifyDocumentFailure,
  createIf2DocumentApi,
  isSafelyEditableBlock,
  pollDocumentExport,
  type DocumentBlock,
  type DocumentBody,
  type DocumentMark,
  type DocumentRevisionRecord,
  type DocumentRichTextBlock,
} from "../../documentWorkflow";
import { useMediaWeb } from "../../MediaWebWorkspace";
import CanonicalDocumentRenderer from "./CanonicalDocumentRenderer";
import { SurfaceState } from "../../ui/SurfaceState";
import styles from "./DocumentEditorPage.module.css";

type SaveState = "clean" | "dirty" | "saving" | "saved" | "conflict" | "offline" | "error";
type MarkName = Exclude<DocumentMark, { type: "link" }>;
const MARKS: readonly MarkName[] = ["bold", "italic", "underline", "strike", "inline_code"];

function cloneBody(body: DocumentBody): DocumentBody { return JSON.parse(JSON.stringify(body)) as DocumentBody; }
function textOf(block: DocumentBlock): string {
  if (block.type === "code_block") return block.text;
  return "content" in block ? block.content.map((run) => run.text).join("") : "";
}
function marksOf(block: DocumentBlock): DocumentMark[] {
  return "content" in block ? block.content[0]?.marks ?? [] : [];
}
function isMark(value: DocumentMark, mark: MarkName): boolean { return value === mark; }

export default function DocumentEditorPage() {
  const { artifactId } = useParams<{ artifactId?: string }>();
  const { runtimeState, session } = useMediaWeb();
  const navigate = useNavigate();
  const api = useMemo(() => createIf2DocumentApi(), []);
  const [revision, setRevision] = useState<DocumentRevisionRecord | null>(null);
  const [body, setBody] = useState<DocumentBody | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("clean");
  const [message, setMessage] = useState("正在读取正文");
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [invalidBlocks, setInvalidBlocks] = useState<string[]>([]);
  const [selectedBlock, setSelectedBlock] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportUrl, setExportUrl] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!artifactId) return;
    setMessage("正在读取正文"); setSaveState("saving"); setErrorCode(null);
    try {
      const response = await api.getBody(artifactId);
      setRevision(response.data.revision); setBody(cloneBody(response.data.revision.body)); setSaveState("clean"); setMessage("已读取最新正文");
    } catch (error) {
      const failure = classifyDocumentFailure(error, "正文暂时不可读取。");
      setMessage(failure.message); setErrorCode(failure.code); setSaveState(failure.kind === "generic" && !navigator.onLine ? "offline" : "error");
    }
  }, [api, artifactId]);
  useEffect(() => { void load(); }, [load]);

  function updateBlock(blockId: string, text: string) {
    setBody((current) => {
      if (!current) return current;
      return { ...current, blocks: current.blocks.map((block) => {
        if (block.id !== blockId || !isSafelyEditableBlock(block)) return block;
        if (block.type === "code_block") return { ...block, text };
        const previous = block.content[0];
        return { ...block, content: [{ type: "text" as const, text, marks: previous?.marks ?? [] }] };
      }) };
    });
    setSaveState("dirty"); setMessage("有未保存修改");
  }
  function toggleMark(mark: MarkName) {
    if (!selectedBlock) return;
    setBody((current) => {
      if (!current) return current;
      return { ...current, blocks: current.blocks.map((block) => {
        if (block.id !== selectedBlock || !("content" in block) || !isSafelyEditableBlock(block)) return block;
        const run = block.content[0] ?? { type: "text" as const, text: "", marks: [] };
        const active = run.marks.some((value) => isMark(value, mark));
        const marks = active ? run.marks.filter((value) => !isMark(value, mark)) : [...run.marks, mark];
        return { ...block, content: [{ ...run, marks }] } as DocumentRichTextBlock;
      }) };
    }); setSaveState("dirty");
  }
  function addLink() {
    if (!selectedBlock) return;
    const href = window.prompt("链接地址");
    if (!href) return;
    setBody((current) => current && { ...current, blocks: current.blocks.map((block) => block.id === selectedBlock && "content" in block ? { ...block, content: [{ ...(block.content[0] ?? { type: "text" as const, text: "" }), marks: [...(block.content[0]?.marks ?? []), { type: "link" as const, href, title: null }] }] } : block) });
    setSaveState("dirty");
  }
  async function save(onlyValid = false) {
    if (!artifactId || !body || !revision || saveState === "saving") return;
    setSaveState("saving"); setMessage("保存中：校验正文"); setErrorCode(null);
    const nextBody = onlyValid && invalidBlocks.length ? { ...body, blocks: body.blocks.filter((block) => !invalidBlocks.includes(block.id)) } : body;
    try {
      setMessage("保存中：写入修订链");
      const response = await api.saveDraft(artifactId, nextBody, revision, { csrfToken: session?.csrfToken ?? "" });
      setRevision(response.data); setBody(cloneBody(response.data.body)); setInvalidBlocks([]); setSaveState("saved"); setMessage("已保存，修订链已更新");
    } catch (error) {
      const failure = classifyDocumentFailure(error, "保存失败，请重试。");
      const status = (error as { status?: number }).status;
      const blockIds = Array.isArray((error as { blockIds?: unknown }).blockIds) ? (error as { blockIds: string[] }).blockIds : [];
      setInvalidBlocks(blockIds); setErrorCode(failure.code); setMessage(failure.message);
      setSaveState(status === 409 || failure.kind === "conflict" ? "conflict" : !navigator.onLine ? "offline" : "error");
    }
  }
  async function exportDocument(format: "pdf" | "docx") {
    if (!artifactId || !revision || !session || exporting || revision.state !== "ready") return;
    setExporting(true); setMessage("正在生成导出文件");
    try {
      const created = await api.createExport(artifactId, revision.revision, format, { csrfToken: session.csrfToken });
      const ready = await pollDocumentExport(api, created.data.publicExportId);
      const download = await api.getExportDownload(ready.publicExportId);
      setExportUrl(download.data.downloadUrl); setMessage(`${format.toUpperCase()} 导出已就绪`);
    } catch (error) { setMessage(classifyDocumentFailure(error, "导出失败，请重试。").message); }
    finally { setExporting(false); }
  }
  if (runtimeState !== "authenticated" || !session) return <SurfaceState kind="permission" title="个人正文编辑" detail="当前会话无权访问正文编辑。" />;
  if (!artifactId || !body || !revision) return <SurfaceState kind="loading" title="个人正文编辑" detail={message} action={<button className="mg-btn mg-btn-soft" onClick={() => void load()}><RefreshCw size={15} />重新读取</button>} />;
  return <main className={styles.page} data-page-ownership="personal" data-accent="studio" data-document-editor="true">
    <header className="mg-hero" data-page-prelude><div><span className="mg-eyebrow">个人正文编辑与修订</span><h1>正文编辑</h1><p className="mg-hero-lead">修订 {revision.revision} · {revision.bodyAuthority === "internal" ? "个人内部正文" : "受保护正文"}</p></div><div className={`${styles.actions} mg-hero-actions`}><button className="mg-btn mg-btn-ghost" onClick={() => navigate(`/workspace/preview/${artifactId}`)}><X size={16}/>关闭</button><button className="mg-btn mg-btn-primary" disabled={saveState === "saving" || saveState === "conflict"} onClick={() => void save()}><Save size={16}/>保存</button></div></header>
    {saveState === "saving" ? <section className={`${styles.banner} ${styles.writing}`} role="status"><strong>保存中</strong><span>{message}</span><ol><li>校验正文</li><li>写入修订链</li><li>记录证据账本</li></ol></section> : null}
    {saveState === "conflict" ? <section className={`${styles.banner} ${styles.conflict}`} role="alert"><strong>发现远端修订冲突</strong><span>{message}</span><div><button className="mg-btn mg-btn-soft" disabled>合并（一期暂不可用）</button><button className="mg-btn mg-btn-primary" onClick={() => void load()}>放弃本地修改</button><button className="mg-btn mg-btn-soft" onClick={() => setSaveState("dirty")}>另存本地副本</button></div><small>{errorCode ?? "document_revision_conflict"}</small></section> : null}
    {saveState === "offline" ? <section className={`${styles.banner} ${styles.offline}`} role="alert"><WifiOff size={18}/><span>{message}</span><button className="mg-btn mg-btn-soft" onClick={() => void save()}>重试保存</button></section> : null}
    {invalidBlocks.length ? <section className={`${styles.banner} ${styles.validation}`} role="alert"><strong>部分正文未通过校验</strong><span>已高亮 {invalidBlocks.length} 个块；可仅保存其余正文。</span><button className="mg-btn mg-btn-soft" onClick={() => void save(true)}>仅保存其余正文</button></section> : null}
    <div className={styles.layout}><section className={`${styles.canvas} mg-panel`} aria-label="正文编辑区"><div className={styles.toolbar}>{MARKS.map((mark) => <button key={mark} type="button" aria-pressed={selectedBlock ? marksOf(body.blocks.find((b) => b.id === selectedBlock)!).some((value) => isMark(value, mark)) : false} onClick={() => toggleMark(mark)}>{mark === "inline_code" ? "代码" : mark === "bold" ? "粗体" : mark === "italic" ? "斜体" : mark === "underline" ? "下划线" : "删除线"}</button>)}<button type="button" onClick={addLink}><LinkIcon size={15}/>链接</button></div><div className={styles.blocks}>{body.blocks.map((block) => <article key={block.id} className={invalidBlocks.includes(block.id) ? styles.invalid : ""} onClick={() => setSelectedBlock(block.id)}>{isSafelyEditableBlock(block) ? <><label htmlFor={`block-${block.id}`}>{block.type.replace("_", " ")}</label><textarea id={`block-${block.id}`} value={textOf(block)} onChange={(event) => updateBlock(block.id, event.target.value)} onFocus={() => setSelectedBlock(block.id)} rows={Math.max(2, Math.min(8, textOf(block).split("\n").length + 1))}/></> : <CanonicalDocumentRenderer blocks={[block]}/>}</article>)}</div></section><aside className={`${styles.side} mg-panel`}><div className={styles.ai}><Sparkles size={17}/><strong>AI 改稿计划</strong><span>功能暂未开放</span></div><h2>证据账本</h2><dl><div><dt>正文校验</dt><dd>服务端保存时执行</dd></div><div><dt>当前修订</dt><dd>{revision.revision}</dd></div><div><dt>正文校验和</dt><dd>{revision.bodyChecksum.slice(0, 16)}…</dd></div></dl><h2>修订链</h2><p className={styles.revision}>r{revision.revision} · {revision.state}<br/><small>基于 {revision.baseRevision ?? "初始正文"}</small></p><div className={styles.export}><h2>导出</h2><button className="mg-btn mg-btn-soft" disabled={exporting || revision.state !== "ready"} onClick={() => void exportDocument("pdf")}><Download size={15}/>PDF</button><button className="mg-btn mg-btn-soft" disabled={exporting || revision.state !== "ready"} onClick={() => void exportDocument("docx")}><Download size={15}/>DOCX</button>{exportUrl ? <a href={exportUrl} target="_blank" rel="noreferrer">下载导出文件</a> : null}</div></aside></div>
  </main>;
}
