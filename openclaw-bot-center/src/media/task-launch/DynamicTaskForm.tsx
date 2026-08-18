import { AlertCircle, FileUp, Paperclip, X } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import type {
  CapabilityDefinition,
  CapabilityField,
} from "../../schemas/capabilityCatalogSchema";
import type { CapabilityParams } from "../../schemas/mediaWebTaskSchema";
import {
  fieldConditionState,
  type DraftIssue,
  type TaskDraft,
} from "./taskDraft";
import {
  isSystemManagedCapabilityField,
  presentCapabilityFieldHelp,
  presentCapabilityFieldLabel,
  presentCapabilityText,
} from "./fieldPresentation";
import { getMaterialParsingPreview } from "./materialParsing";

export function DynamicTaskForm({
  capability,
  draft,
  onVariant,
  onField,
  onUploads,
}: {
  capability: CapabilityDefinition;
  draft: TaskDraft;
  onVariant: (variantId: string) => void;
  onField: (key: string, value: CapabilityParams[string]) => void;
  onUploads: (files: File[]) => void;
}) {
  const firstErrorRef = useRef<
    HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null
  >(null);
  const issueMap = useMemo(
    () =>
      new Map(
        draft.issues
          .filter((item) => item.fieldKey)
          .map((item) => [item.fieldKey, item]),
      ),
    [draft.issues],
  );
  const variant =
    capability.variants.find((item) => item.variantId === draft.variantId) ??
    capability.variants[0];
  const visibleFields = capability.fields.filter(
    (field) => !isSystemManagedCapabilityField(field),
  );
  const visibleFieldKeys = new Set(visibleFields.map((field) => field.key));
  const required = new Set([
    ...(variant?.requiredFields ?? []).filter((key) =>
      visibleFieldKeys.has(key),
    ),
    ...visibleFields.filter((item) => item.required).map((item) => item.key),
  ]);
  const anyGroups = (variant?.requiredAnyOf ?? [])
    .map((group) => group.filter((key) => visibleFieldKeys.has(key)))
    .filter((group) => group.length > 0);
  const forbidden = new Set(variant?.forbiddenFields ?? []);
  const applicableFields = visibleFields.filter(
    (field) =>
      !forbidden.has(field.key) && fieldConditionState(field, draft).visible,
  );
  const requiredFields = applicableFields.filter((field) =>
    required.has(field.key),
  );
  const optionalFields = applicableFields.filter(
    (field) => !required.has(field.key),
  );
  const materialParsing = getMaterialParsingPreview({
    capabilityId: capability.capabilityId,
    params: draft.params,
    uploads: draft.uploads,
  });
  const shouldShowMaterialUpload =
    materialParsing.applicable && materialParsing.sourceKind === "file";
  const shouldShowCapabilityUpload = capability.supportedAttachments.some(
    (item) => !["text", "url"].includes(item),
  );
  const uploadAccept = materialParsing.materialTypeId === "image"
    ? "image/*"
    : materialParsing.materialTypeId === "audio"
      ? "audio/*"
      : materialParsing.materialTypeId === "video"
        ? "video/*"
        : materialParsing.materialTypeId === "pdf"
          ? "application/pdf"
          : undefined;
  let firstErrorAssigned = false;

  useEffect(() => {
    if (
      draft.phase === "editing" &&
      draft.issues.length &&
      firstErrorRef.current
    )
      firstErrorRef.current.focus();
  }, [draft.phase, draft.issues]);

  return (
    <section
      className="task-launch-section dynamic-task-form"
      aria-labelledby="dynamic-form-title"
    >
      <div className="task-launch-section-heading">
        <span>3</span>
        <div>
          <h3 id="dynamic-form-title">任务信息</h3>
          <p>
            {capability.hierarchy.pathNames
              .map(presentTaskText)
              .join(" / ")}
          </p>
        </div>
      </div>
      {capability.variants.length > 1 ? (
        <fieldset className="variant-control">
          <legend>
            具体操作 <b>*</b>
          </legend>
          <div>
            {capability.variants.map((item) => (
              <button
                type="button"
                key={item.variantId}
                className={item.variantId === draft.variantId ? "active" : ""}
                onClick={() => onVariant(item.variantId)}
              >
                {presentTaskText(item.label)}
              </button>
            ))}
          </div>
        </fieldset>
      ) : null}
      {anyGroups.map((group) => (
        <div className="required-group-note" key={group.join("-")}>
          <strong>
            {group
              .map((key) => {
                const field = capability.fields.find(
                  (item) => item.key === key,
                );
                return field ? displayFieldLabel(field) : presentFieldText(key);
              })
              .join("或")}{" "}
            *
          </strong>
          <span>至少填写其中一项</span>
        </div>
      ))}
      {materialParsing.applicable ? (
        <section
          className={`material-parsing-panel ${materialParsing.canConfirm ? "is-ready" : "is-incomplete"}`}
          aria-labelledby="material-parsing-title"
          data-material-parsing-status={materialParsing.expectedStatus ?? "incomplete"}
        >
          <div className="material-parsing-panel-heading">
            <div>
              <h4 id="material-parsing-title">素材解析预览</h4>
              <p>
                {materialParsing.platformLabel} · {materialParsing.materialTypeLabel}
              </p>
            </div>
            <strong>{materialParsing.methodLabel}</strong>
          </div>
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
      {requiredFields.length ? (
        <section className="task-field-group required-field-group" aria-labelledby="required-fields-title">
          <h4 id="required-fields-title">必填信息</h4>
          <div className="dynamic-fields">
            {requiredFields.map((field) => {
            const receivesErrorFocus =
              issueMap.has(field.key) && !firstErrorAssigned;
            if (receivesErrorFocus) firstErrorAssigned = true;
            const conditionState = fieldConditionState(field, draft);
            return (
              <DynamicField
                key={field.key}
                field={field}
                value={draft.params[field.key]}
                required={required.has(field.key)}
                issue={issueMap.get(field.key)}
                provenance={draft.provenance[field.key]}
                disabled={!conditionState.enabled}
                inputRef={receivesErrorFocus ? firstErrorRef : undefined}
                onChange={(value) => onField(field.key, value)}
              />
            );
            })}
          </div>
        </section>
      ) : null}
      {optionalFields.length ? (
        <section className="task-field-group optional-field-group" aria-labelledby="optional-fields-title">
          <h4 id="optional-fields-title">补充信息</h4>
          <div className="dynamic-fields">
            {optionalFields.map((field) => {
            const receivesErrorFocus =
              issueMap.has(field.key) && !firstErrorAssigned;
            if (receivesErrorFocus) firstErrorAssigned = true;
            const conditionState = fieldConditionState(field, draft);
            return (
              <DynamicField
                key={field.key}
                field={field}
                value={draft.params[field.key]}
                required={required.has(field.key)}
                issue={issueMap.get(field.key)}
                provenance={draft.provenance[field.key]}
                disabled={!conditionState.enabled}
                inputRef={receivesErrorFocus ? firstErrorRef : undefined}
                onChange={(value) => onField(field.key, value)}
              />
            );
          })}
          </div>
        </section>
      ) : null}
      {shouldShowMaterialUpload || shouldShowCapabilityUpload ? (
        <div className="dynamic-upload">
          <label>
            <Paperclip size={16} />
            <span>
              {draft.uploads.length
                ? `已选择 ${draft.uploads.length} 个文件`
                : "添加文件"}
            </span>
            <input
              type="file"
              multiple
              accept={uploadAccept}
              onChange={(event) => onUploads([...(event.target.files ?? [])])}
            />
          </label>
          {draft.uploads.length ? (
            <div className="upload-list">
              {draft.uploads.map((file) => (
                <span key={`${file.name}-${file.size}`}>
                  <FileUp size={14} />
                  {file.name}
                  <button
                    type="button"
                    aria-label={`移除 ${file.name}`}
                    onClick={() =>
                      onUploads(draft.uploads.filter((item) => item !== file))
                    }
                  >
                    <X size={13} />
                  </button>
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      {draft.issues
        .filter((item) => !item.fieldKey)
        .map((issue) => (
          <p
            className="form-error"
            role="alert"
            key={`${issue.code}-${issue.message}`}
          >
            <AlertCircle size={15} />
            {presentFieldText(issue.message)}
          </p>
        ))}
    </section>
  );
}

function DynamicField({
  field,
  value,
  required,
  issue,
  provenance,
  disabled,
  inputRef,
  onChange,
}: {
  field: CapabilityField;
  value: CapabilityParams[string] | undefined;
  required: boolean;
  issue?: DraftIssue;
  provenance?: string;
  disabled: boolean;
  inputRef?: React.MutableRefObject<
    HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null
  >;
  onChange: (value: CapabilityParams[string]) => void;
}) {
  const common = {
    id: `task-field-${field.key}`,
    disabled,
    "aria-invalid": Boolean(issue),
    "aria-describedby": issue ? `task-field-${field.key}-error` : undefined,
  };
  let control;
  if (field.inputType === "textarea")
    control = (
      <textarea
        {...common}
        ref={inputRef as React.Ref<HTMLTextAreaElement>}
        rows={4}
        value={typeof value === "string" ? value : ""}
        placeholder={presentTaskText(presentCapabilityFieldHelp(field))}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  else if (field.inputType === "select")
    control = (
      <select
        {...common}
        ref={inputRef as React.Ref<HTMLSelectElement>}
        value={typeof value === "string" ? value : ""}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">请选择</option>
        {field.options.map((item) => (
          <option value={item.value} key={item.value}>
            {presentTaskText(item.label)}
          </option>
        ))}
      </select>
    );
  else if (field.inputType === "radio")
    control = (
      <fieldset
        className="dynamic-radio"
        aria-invalid={Boolean(issue)}
        disabled={disabled}
      >
        {field.options.map((item, index) => (
          <label key={item.value}>
            <input
              ref={
                index === 0
                  ? (inputRef as React.Ref<HTMLInputElement>)
                  : undefined
              }
              type="radio"
              name={common.id}
              value={item.value}
              checked={value === item.value}
              onChange={() => onChange(item.value)}
            />
            <span>{presentTaskText(item.label)}</span>
          </label>
        ))}
      </fieldset>
    );
  else if (field.inputType === "multiselect" && field.options.length)
    control = (
      <fieldset
        className="dynamic-multiselect"
        aria-invalid={Boolean(issue)}
        disabled={disabled}
      >
        {field.options.map((item, index) => (
          <label key={item.value}>
            <input
              ref={
                index === 0
                  ? (inputRef as React.Ref<HTMLInputElement>)
                  : undefined
              }
              type="checkbox"
              checked={Array.isArray(value) && value.includes(item.value)}
              onChange={(event) => {
                const current = Array.isArray(value) ? value.map(String) : [];
                onChange(
                  event.target.checked
                    ? [...current, item.value]
                    : current.filter((entry) => entry !== item.value),
                );
              }}
            />
            <span>{presentTaskText(item.label)}</span>
          </label>
        ))}
      </fieldset>
    );
  else if (field.inputType === "multiselect")
    control = (
      <input
        {...common}
        ref={inputRef as React.Ref<HTMLInputElement>}
        value={Array.isArray(value) ? value.join("、") : ""}
        placeholder={presentTaskText(presentCapabilityFieldHelp(field))}
        onChange={(event) =>
          onChange(
            event.target.value
              .split(/[、,，]/)
              .map((item) => item.trim())
              .filter(Boolean),
          )
        }
      />
    );
  else if (field.inputType === "object")
    control = (
      <>
        <input
          {...common}
          ref={inputRef as React.Ref<HTMLInputElement>}
          list={`${common.id}-options`}
          value={typeof value === "string" ? value : ""}
          placeholder={presentTaskText(field.placeholder)}
          onChange={(event) => onChange(event.target.value)}
        />
        {field.options.length ? (
          <datalist id={`${common.id}-options`}>
            {field.options.map((item) => (
              <option value={item.value} key={item.value}>
                {presentTaskText(item.label)}
              </option>
            ))}
          </datalist>
        ) : null}
      </>
    );
  else if (field.inputType === "number")
    control = (
      <input
        {...common}
        ref={inputRef as React.Ref<HTMLInputElement>}
        type="number"
        value={typeof value === "number" ? value : ""}
        placeholder={presentTaskText(presentCapabilityFieldHelp(field))}
        onChange={(event) =>
          onChange(
            event.target.value === "" ? null : Number(event.target.value),
          )
        }
      />
    );
  else
    control = (
      <input
        {...common}
        ref={inputRef as React.Ref<HTMLInputElement>}
        type={
          field.inputType === "url"
            ? "url"
            : field.inputType === "date"
              ? "date"
              : "text"
        }
        value={typeof value === "string" ? value : ""}
        placeholder={presentTaskText(presentCapabilityFieldHelp(field))}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  const heading = (
    <span>
      {displayFieldLabel(field)}
      {required ? <b> *</b> : null}
      {provenance === "ai" ? (
        <em>AI 已填</em>
      ) : provenance === "user-edited" ? (
        <em>已修改</em>
      ) : null}
    </span>
  );
  return field.inputType === "radio" ||
    (field.inputType === "multiselect" && field.options.length) ? (
    <div className={`dynamic-field ${issue ? "has-error" : ""}`}>
      {heading}
      {control}
      {issue ? (
        <small id={`${common.id}-error`} role="alert">
          {presentFieldText(issue.message)}
        </small>
      ) : null}
    </div>
  ) : (
    <label
      className={`dynamic-field ${issue ? "has-error" : ""}`}
      htmlFor={common.id}
    >
      {heading}
      {control}
      {issue ? (
        <small id={`${common.id}-error`} role="alert">
          {presentFieldText(issue.message)}
        </small>
      ) : null}
    </label>
  );
}

function presentFieldText(value: string) {
  return presentTaskText(value);
}

function displayFieldLabel(field: CapabilityField) {
  return presentTaskText(presentCapabilityFieldLabel(field));
}

const FRONTEND_LABEL_REPLACEMENTS: ReadonlyArray<readonly [RegExp, string]> = [
  [
    /\bidempotency[\s_-]*receipt[\s_-]*id\b/gi,
    "重复提交保护编号",
  ],
  [/\bidempotency[\s_-]*receipt\b/gi, "重复提交保护"],
  [/\bsub[\s_-]*agents?[\s_-]*count\b/gi, "协作助手数量"],
  [/\bsub[\s_-]*agents?\b/gi, "协作助手"],
];

function presentTaskText(value: string) {
  const normalized = FRONTEND_LABEL_REPLACEMENTS.reduce(
    (text, [pattern, replacement]) => text.replace(pattern, replacement),
    value,
  );
  return presentCapabilityText(normalized);
}
