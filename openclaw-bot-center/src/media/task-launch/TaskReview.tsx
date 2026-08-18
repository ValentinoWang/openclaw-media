import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  LoaderCircle,
  Search,
  Send,
  Trash2,
} from "lucide-react";
import type { CapabilityDefinition } from "../../schemas/capabilityCatalogSchema";
import type { TaskDraft } from "./taskDraft";
import {
  confirmationReceiptProblem,
  confirmationReceiptProblemMessage,
} from "../confirmationReceiptExpiry";
import {
  isSystemManagedCapabilityField,
  presentCapabilityFieldLabel,
  presentCapabilityText,
} from "./fieldPresentation";
import { getMaterialParsingPreview } from "./materialParsing";

export function TaskReview({
  draft,
  capability,
  onEdit,
  onSubmit,
}: {
  draft: TaskDraft;
  capability: CapabilityDefinition;
  onEdit: () => void;
  onSubmit: () => void;
}) {
  const deletionPreview =
    capability.capabilityId === "universal_deletion" &&
    draft.variantId === "preview";
  const deletionConfirm =
    capability.capabilityId === "universal_deletion" &&
    draft.variantId === "confirm";
  const materialParsing = getMaterialParsingPreview({
    capabilityId: capability.capabilityId,
    params: draft.params,
    uploads: draft.uploads,
  });
  const materialParsingBlocked =
    materialParsing.applicable && !materialParsing.canConfirm;
  const materialParsingError = [
    materialParsing.failureReason,
    materialParsing.missingFields.length
      ? `缺少：${materialParsing.missingFields.join("、")}。`
      : "",
    materialParsing.nextAction,
  ]
    .filter(Boolean)
    .join(" ");
  const receiptProblem = confirmationReceiptProblem(
    draft.capabilityId,
    draft.variantId,
    draft.confirmationReceipt,
  ) ?? (materialParsingBlocked ? "material_parsing_incomplete" : null);
  const receiptError = materialParsingBlocked
    ? materialParsingError
    : receiptProblem && receiptProblem !== "material_parsing_incomplete"
      ? confirmationReceiptProblemMessage(receiptProblem)
      : "";
  const values = capability.fields.filter((field) => {
    if (isSystemManagedCapabilityField(field)) return false;
    if (deletionConfirm && field.key === "action") return false;
    const value = draft.params[field.key];
    return (
      value !== undefined &&
      value !== "" &&
      value !== null &&
      (!Array.isArray(value) || value.length > 0)
    );
  });
  return (
    <section
      className="task-launch-section task-review"
      aria-labelledby="task-review-title"
    >
      <div className="task-launch-section-heading">
        <span aria-hidden="true">
          {deletionPreview ? (
            <Search size={14} />
          ) : deletionConfirm ? (
            <Trash2 size={14} />
          ) : (
            <CheckCircle2 size={14} />
          )}
        </span>
        <div>
          <h3 id="task-review-title">
            {deletionPreview
              ? "生成删除预览"
              : deletionConfirm
                ? "确认删除"
                : "确认并提交"}
          </h3>
          <p>
            {deletionPreview
              ? "只读取影响范围，不会删除素材或关联记录。"
              : deletionConfirm
                ? "确认后将删除目标及其关联数据。"
                : "任务创建前最后核对一次。"}
          </p>
        </div>
      </div>
      {materialParsing.applicable ? (
        <section
          className={`material-parsing-summary ${materialParsing.canConfirm ? "is-ready" : "is-incomplete"}`}
          aria-labelledby="task-review-material-parsing-title"
          data-material-parsing-status={materialParsing.expectedStatus ?? "incomplete"}
        >
          <h4 id="task-review-material-parsing-title">素材解析确认</h4>
          <dl>
            <div>
              <dt>解析方式</dt>
              <dd>{materialParsing.methodLabel}</dd>
            </div>
            <div>
              <dt>预期状态</dt>
              <dd>{materialParsing.expectedStatusLabel}</dd>
            </div>
            <div>
              <dt>失败原因</dt>
              <dd>{materialParsing.failureReason || "无"}</dd>
            </div>
            <div>
              <dt>缺失字段</dt>
              <dd>{materialParsing.missingFields.join("、") || "无"}</dd>
            </div>
            <div>
              <dt>人工补充结果</dt>
              <dd>{materialParsing.manualSupplementResult}</dd>
            </div>
            <div>
              <dt>下一步</dt>
              <dd>{materialParsing.nextAction}</dd>
            </div>
          </dl>
        </section>
      ) : null}
      <dl>
        <div>
          <dt>{deletionPreview || deletionConfirm ? "操作" : "任务能力"}</dt>
          <dd>
            {deletionPreview
              ? "预览删除影响"
              : deletionConfirm
                ? "确认删除"
                : presentCapabilityText(capability.displayName)}
          </dd>
        </div>
        {values.map((field) => {
          const value = draft.params[field.key];
          return (
            <div key={field.key}>
              <dt>{presentCapabilityFieldLabel(field)}</dt>
              <dd>{Array.isArray(value) ? value.join("、") : String(value)}</dd>
            </div>
          );
        })}
        {draft.uploads.length ? (
          <div>
            <dt>附件</dt>
            <dd>{draft.uploads.map((file) => file.name).join("、")}</dd>
          </div>
        ) : null}
      </dl>
      {draft.error || receiptError ? (
        <p className="form-error" role="alert">
          <AlertCircle size={15} />
          {receiptError || draft.error}
        </p>
      ) : null}
      <div className={`review-actions ${deletionConfirm ? "is-confirm-only" : ""}`}>
        {!deletionConfirm ? (
          <button type="button" onClick={onEdit}>
            <ArrowLeft size={16} />
            返回修改
          </button>
        ) : null}
        <button
          type="button"
          className={deletionConfirm ? "danger-button" : "primary-button"}
          disabled={draft.phase === "submitting" || receiptProblem !== null}
          onClick={onSubmit}
        >
          {draft.phase === "submitting" ? (
            <LoaderCircle className="spin" size={16} />
          ) : deletionConfirm ? (
            <Trash2 size={16} />
          ) : (
            <Send size={16} />
          )}
          {receiptProblem === "material_parsing_incomplete"
            ? "返回修改"
            : receiptProblem
            ? "预览已过期"
            : draft.phase === "submitting"
            ? deletionPreview
              ? "正在生成预览"
              : deletionConfirm
                ? "正在确认删除"
              : "正在提交"
            : deletionPreview
              ? "生成删除预览"
              : deletionConfirm
                ? "确认删除"
              : "提交任务"}
        </button>
      </div>
    </section>
  );
}
