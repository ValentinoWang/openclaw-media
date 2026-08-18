import materialParsingContractJson from "../../../contracts/material-parsing-coverage-v1.json" with {
  type: "json",
};

export const MATERIAL_PARSING_CAPABILITY_ID = "source_asset_intake";
export const MATERIAL_TYPE_FIELD_KEY = "field_3be96f8eb83d";
export const PLATFORM_FIELD_KEY = "platform";
export const SOURCE_CONTENT_FIELD_KEY = "field_c675ffae69a2";
export const MANUAL_SUPPLEMENT_FIELD_KEY = "remark";

type MaterialParsingMode = "automatic" | "manual_required";
export type MaterialParsingCompletionStatus =
  | "completed_auto"
  | "completed_manual";
export type MaterialParsingSourceKind = "text" | "url" | "file";

type MaterialParsingValue = { id: string; label: string };

type MaterialParsingCoverage = {
  platform: string;
  materialType: string;
  mode: MaterialParsingMode;
  parserId: string;
  parserVersion: string;
  requiredOutputs: string[];
  failureCode: string;
  failurePrompt: string;
  manualFields: string[];
  nextAction: string;
};

type MaterialParsingContract = {
  schemaVersion: string;
  contractId: string;
  decisionVersion: number;
  statuses: string[];
  completionStatuses: string[];
  platforms: MaterialParsingValue[];
  materialTypes: MaterialParsingValue[];
  manualSupplementField: string;
  sourceFields: Record<string, string>;
  coverage: MaterialParsingCoverage[];
};

export type MaterialParsingPreview = {
  applicable: boolean;
  platformId: string | null;
  platformLabel: string;
  materialTypeId: string | null;
  materialTypeLabel: string;
  sourceKind: MaterialParsingSourceKind | null;
  mode: MaterialParsingMode | null;
  methodLabel: string;
  expectedStatus: MaterialParsingCompletionStatus | null;
  expectedStatusLabel: string;
  failureReason: string;
  missingFields: string[];
  missingFieldKeys: string[];
  manualSupplement: string;
  manualSupplementResult: string;
  nextAction: string;
  failureCode: string;
  canConfirm: boolean;
};

type MaterialParsingDraftInput = {
  capabilityId: string;
  params: Readonly<Record<string, unknown>>;
  uploads: ReadonlyArray<File>;
};

const MANUAL_SUPPLEMENT_LABEL = "补充说明";
const SOURCE_CONTENT_LABEL = "链接或文字素材";
const UPLOAD_LABEL = "草稿附件";
const SERVER_FIELD_LABELS: Record<string, string> = {
  [MATERIAL_TYPE_FIELD_KEY]: "素材类型",
  [PLATFORM_FIELD_KEY]: "平台",
  [SOURCE_CONTENT_FIELD_KEY]: SOURCE_CONTENT_LABEL,
  uploadIds: "上传文件",
  "uploadIds.mimeType": "上传文件类型",
  sourceUrl: "来源链接",
  title: "标题",
  content: "正文",
  [MANUAL_SUPPLEMENT_FIELD_KEY]: MANUAL_SUPPLEMENT_LABEL,
};

export const materialParsingContract = loadMaterialParsingContract(
  materialParsingContractJson as unknown,
);

const coverageByKey = new Map(
  materialParsingContract.coverage.map((item) => [
    `${item.platform}:${item.materialType}`,
    item,
  ]),
);

export function getMaterialParsingPreview(
  input: MaterialParsingDraftInput,
): MaterialParsingPreview {
  if (input.capabilityId !== MATERIAL_PARSING_CAPABILITY_ID) {
    return {
      applicable: false,
      platformId: null,
      platformLabel: "",
      materialTypeId: null,
      materialTypeLabel: "",
      sourceKind: null,
      mode: null,
      methodLabel: "",
      expectedStatus: null,
      expectedStatusLabel: "",
      failureReason: "",
      missingFields: [],
      missingFieldKeys: [],
      manualSupplement: "",
      manualSupplementResult: "",
      nextAction: "",
      failureCode: "",
      canConfirm: true,
    };
  }

  const platform = resolveValue(input.params[PLATFORM_FIELD_KEY], materialParsingContract.platforms);
  const materialType = resolveValue(
    input.params[MATERIAL_TYPE_FIELD_KEY],
    materialParsingContract.materialTypes,
  );
  const platformValue = readValue(input.params[PLATFORM_FIELD_KEY]);
  const materialTypeValue = readValue(input.params[MATERIAL_TYPE_FIELD_KEY]);
  const platformLabel = platform?.label ?? (platformValue || "未选择");
  const materialTypeLabel = materialType?.label ?? (materialTypeValue || "未选择");
  const sourceKind = sourceKindFor(materialType?.id ?? null);
  const manualSupplement = readValue(input.params[MANUAL_SUPPLEMENT_FIELD_KEY]);
  const sourcePresent = hasSource(input, sourceKind);

  if (!platform || !materialType) {
    const missingFieldKeys = [
      !materialType ? MATERIAL_TYPE_FIELD_KEY : null,
      !platform ? PLATFORM_FIELD_KEY : null,
    ].filter((key): key is string => Boolean(key));
    const missingFields = missingFieldKeys.map((key) =>
      key === MATERIAL_TYPE_FIELD_KEY ? "素材类型" : "平台",
    );
    return {
      applicable: true,
      platformId: platform?.id ?? null,
      platformLabel,
      materialTypeId: materialType?.id ?? null,
      materialTypeLabel,
      sourceKind,
      mode: null,
      methodLabel: "无法确定解析方式",
      expectedStatus: null,
      expectedStatusLabel: "无法确认",
      failureReason: "当前素材类型和平台无法对应到唯一的解析合同。",
      missingFields,
      missingFieldKeys,
      manualSupplement,
      manualSupplementResult: manualSupplement
        ? `已填写人工补充：${manualSupplement}`
        : "未填写",
      nextAction: "请选择合同中的素材类型和平台后重新校验。",
      failureCode: "material_parsing_combination_missing",
      canConfirm: false,
    };
  }

  const coverage = coverageByKey.get(`${platform.id}:${materialType.id}`);
  if (!coverage) {
    return {
      applicable: true,
      platformId: platform.id,
      platformLabel: platform.label,
      materialTypeId: materialType.id,
      materialTypeLabel: materialType.label,
      sourceKind,
      mode: null,
      methodLabel: "无法确定解析方式",
      expectedStatus: null,
      expectedStatusLabel: "无法确认",
      failureReason: "当前组合不在素材解析合同中，不能默认支持。",
      missingFields: [],
      missingFieldKeys: [],
      manualSupplement,
      manualSupplementResult: manualSupplement
        ? `已填写人工补充：${manualSupplement}`
        : "未填写",
      nextAction: "请选择合同中的平台和素材类型组合后重新校验。",
      failureCode: "material_parsing_combination_unsupported",
      canConfirm: false,
    };
  }

  const missingFieldKeys: string[] = [];
  const missingFields: string[] = [];
  if (!sourcePresent) {
    const sourceFieldKey = sourceKind === "file" ? "uploadIds" : SOURCE_CONTENT_FIELD_KEY;
    missingFieldKeys.push(sourceFieldKey);
    missingFields.push(sourceKind === "file" ? UPLOAD_LABEL : SOURCE_CONTENT_LABEL);
  }
  if (coverage.mode === "manual_required" && !manualSupplement) {
    missingFieldKeys.push(MANUAL_SUPPLEMENT_FIELD_KEY);
    missingFields.push(MANUAL_SUPPLEMENT_LABEL);
  }

  if (missingFields.length) {
    const sourceMissing = !sourcePresent;
    const failureReason = sourceMissing
      ? `${coverage.failurePrompt}${sourceKind === "file" ? " 未上传草稿附件。" : " 原始文本或链接不能为空。"}`
      : coverage.failurePrompt;
    const nextAction = sourceMissing
      ? coverage.mode === "manual_required"
        ? "请先提供原始素材并填写人工补充后重新校验。"
        : `请补充${sourceKind === "file" ? "草稿附件" : "原始文本或链接"}后重新校验。`
      : coverage.nextAction;
    return {
      applicable: true,
      platformId: platform.id,
      platformLabel: platform.label,
      materialTypeId: materialType.id,
      materialTypeLabel: materialType.label,
      sourceKind,
      mode: coverage.mode,
      methodLabel:
        coverage.mode === "automatic"
          ? "支持自动解析，提交时校验"
          : "需要人工补充",
      expectedStatus:
        coverage.mode === "automatic" ? "completed_auto" : "completed_manual",
      expectedStatusLabel: completionStatusLabel(
        coverage.mode === "automatic" ? "completed_auto" : "completed_manual",
      ),
      failureReason,
      missingFields,
      missingFieldKeys,
      manualSupplement,
      manualSupplementResult: manualSupplement
        ? `已填写人工补充：${manualSupplement}`
        : "尚未填写人工补充。",
      nextAction,
      failureCode: sourceMissing ? "material_source_missing" : coverage.failureCode,
      canConfirm: false,
    };
  }

  const isAutomatic = coverage.mode === "automatic";
  return {
    applicable: true,
    platformId: platform.id,
    platformLabel: platform.label,
    materialTypeId: materialType.id,
    materialTypeLabel: materialType.label,
    sourceKind,
    mode: coverage.mode,
    methodLabel: isAutomatic ? "支持自动解析，提交时校验" : "需要人工补充",
    expectedStatus: isAutomatic ? "completed_auto" : "completed_manual",
    expectedStatusLabel: completionStatusLabel(
      isAutomatic ? "completed_auto" : "completed_manual",
    ),
    failureReason: isAutomatic
      ? "自动解析结果将在提交时由后端校验。"
      : coverage.failurePrompt,
    missingFields: [],
    missingFieldKeys: [],
    manualSupplement,
    manualSupplementResult: manualSupplement
      ? `已填写人工补充：${manualSupplement}${isAutomatic ? "（自动解析失败时用于人工复验，不会显示为自动成功）" : "（不会显示为自动成功）"}`
      : isAutomatic
        ? "未填写（自动解析路径不要求人工补充）。"
        : "已填写人工补充。",
    nextAction: isAutomatic ? "提交时校验自动解析结果。" : coverage.nextAction,
    failureCode: isAutomatic ? "" : coverage.failureCode,
    canConfirm: true,
  };
}

export function materialParsingIssues(
  input: MaterialParsingDraftInput,
): Array<{
  code: string;
  fieldKey?: string;
  ruleType: string;
  message: string;
}> {
  const preview = getMaterialParsingPreview(input);
  if (!preview.applicable || preview.canConfirm) return [];
  const missing = preview.missingFields.length
    ? `缺少：${preview.missingFields.join("、")}。`
    : "";
  return [
    {
      code: preview.failureCode || "material_parsing_incomplete",
      fieldKey: preview.missingFieldKeys[0],
      ruleType: "material_parsing",
      message: `${preview.failureReason} ${missing}${preview.nextAction}`.trim(),
    },
  ];
}

export function materialParsingServerFailureMessage(
  code: string,
  message: unknown,
  details: unknown,
): string {
  if (code !== "material_parsing_incomplete") {
    return typeof message === "string" && message.trim()
      ? message.trim()
      : "任务未完成，请稍后重试。";
  }
  const detail = asRecord(details);
  const failureReason = readValue(
    detail?.failurePrompt ?? detail?.failureReason ?? detail?.reason,
  );
  const missingFields = Array.isArray(detail?.missingFields)
    ? detail.missingFields.filter(
        (item): item is string =>
          typeof item === "string" && item.trim().length > 0,
      ).map((item) => SERVER_FIELD_LABELS[item] ?? item)
    : [];
  const nextAction = readValue(detail?.nextAction ?? detail?.action);
  const parts = [
    typeof message === "string" && message.trim() ? message.trim() : "素材解析未完成。",
    failureReason,
    missingFields.length ? `缺少：${missingFields.join("、")}。` : "",
    nextAction,
    "请返回修改后重新校验。",
  ].filter(Boolean);
  return [...new Set(parts)].join(" ");
}

function loadMaterialParsingContract(value: unknown): MaterialParsingContract {
  const contract = asRecord(value);
  if (!contract || contract.schemaVersion !== "1" || contract.contractId !== "media-material-parsing-coverage-v1") {
    throw new Error("素材解析合同版本不受支持。");
  }
  const platforms = readValues(contract.platforms, "platforms");
  const materialTypes = readValues(contract.materialTypes, "materialTypes");
  const coverage = contract.coverage;
  if (!Array.isArray(coverage) || coverage.length !== 54) {
    throw new Error("素材解析合同必须包含 54 项唯一组合。");
  }
  const keys = coverage.map((item) => {
    const record = asRecord(item);
    if (!record) throw new Error("素材解析合同包含无效矩阵项。");
    const mode = record.mode;
    if (mode !== "automatic" && mode !== "manual_required") {
      throw new Error("素材解析合同包含无效解析方式。");
    }
    if (
      typeof record.parserId !== "string" ||
      typeof record.parserVersion !== "string" ||
      typeof record.failurePrompt !== "string" ||
      typeof record.failureCode !== "string" ||
      typeof record.nextAction !== "string" ||
      !Array.isArray(record.requiredOutputs) ||
      !Array.isArray(record.manualFields)
    ) {
      throw new Error("素材解析合同矩阵项字段不完整。");
    }
    return `${String(record.platform)}:${String(record.materialType)}`;
  });
  if (new Set(keys).size !== 54) throw new Error("素材解析合同存在重复组合。");
  const platformIds = new Set(platforms.map((item) => item.id));
  const materialTypeIds = new Set(materialTypes.map((item) => item.id));
  for (const key of keys) {
    const [platform, materialType] = key.split(":");
    if (!platformIds.has(platform) || !materialTypeIds.has(materialType)) {
      throw new Error("素材解析合同包含未声明的平台或素材类型。");
    }
  }
  if (platforms.length !== 9 || materialTypes.length !== 6) {
    throw new Error("素材解析合同的平台或素材类型数量不正确。");
  }
  return contract as unknown as MaterialParsingContract;
}

function readValues(value: unknown, fieldName: string): MaterialParsingValue[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error(`素材解析合同缺少 ${fieldName}。`);
  }
  const values = value.map((item) => {
    const record = asRecord(item);
    if (!record || typeof record.id !== "string" || typeof record.label !== "string") {
      throw new Error(`素材解析合同的 ${fieldName} 无效。`);
    }
    return { id: record.id, label: record.label };
  });
  if (new Set(values.map((item) => item.id)).size !== values.length) {
    throw new Error(`素材解析合同的 ${fieldName} 存在重复项。`);
  }
  return values;
}

function resolveValue(value: unknown, values: readonly MaterialParsingValue[]) {
  const normalized = readValue(value);
  return values.find((item) => item.id === normalized || item.label === normalized) ?? null;
}

function sourceKindFor(materialType: string | null): MaterialParsingSourceKind | null {
  if (materialType === "text") return "text";
  if (materialType === "url") return "url";
  if (["image", "audio", "video", "pdf"].includes(materialType ?? "")) return "file";
  return null;
}

function hasSource(
  input: MaterialParsingDraftInput,
  sourceKind: MaterialParsingSourceKind | null,
): boolean {
  if (sourceKind === "file") return input.uploads.length > 0;
  if (sourceKind === "text" || sourceKind === "url") {
    return Boolean(readValue(input.params[SOURCE_CONTENT_FIELD_KEY]));
  }
  return false;
}

function completionStatusLabel(status: MaterialParsingCompletionStatus): string {
  return status === "completed_auto" ? "自动解析完成（提交时校验）" : "人工补充完成";
}

function readValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
