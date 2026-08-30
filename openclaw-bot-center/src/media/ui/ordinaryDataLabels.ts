const TRACK_STATUS_LABELS: Record<string, string> = {
  active: "使用中",
  draft: "草稿",
  archived: "已归档",
  paused: "已暂停",
};

const OPERATIONAL_STATUS_LABELS: Record<string, string> = {
  active: "运营中",
  paused: "暂停运营",
  disabled: "已停用",
};

const OWNED_ACCOUNT_DATA_SOURCE_LABELS: Record<string, string> = {
  feishu_creator_profile: "飞书达人账号档案",
};

const CREATOR_ROLE_LABELS: Record<string, string> = {
  creator: "内容创作者",
  influencer: "内容创作者",
  brand: "品牌账号",
  organization: "机构账号",
  media: "媒体账号",
};

const RELATIONSHIP_ROLE_LABELS: Record<string, string> = {
  标杆账号: "标杆账号",
  竞品账号: "竞品账号",
  合作候选: "合作候选",
  素材来源: "素材来源",
  同赛道观察: "同赛道观察",
  风险账号: "风险账号",
  creator: "创作者",
  observer: "观察对象",
  reference: "参考对象",
  competitor: "竞品参考",
};

const RELATIONSHIP_STATUS_LABELS: Record<string, string> = {
  candidate: "待确认",
  active: "已纳入",
  rejected: "已排除",
};

const INVITE_STATUS_LABELS: Record<string, string> = {
  pending: "待接受",
  accepted: "已接受",
  expired: "已过期",
  revoked: "已撤销",
};

const QUALITY_LABELS: Record<string, string> = {
  verified: "已验证",
  partial: "部分验证",
  unverified: "未验证",
  unavailable: "暂不可用",
};

const MEDIA_TYPE_LABELS: Record<string, string> = {
  image: "图片",
  图片: "图片",
  video: "视频",
  视频: "视频",
  audio: "音频",
  document: "文档",
  link: "链接",
  链接: "链接",
  text: "文本",
};

const MATERIAL_STATUS_LABELS: Record<string, string> = {
  parsed: "已解析",
  parsing: "解析中",
  migrated: "已迁移",
  migrating: "迁移中",
  pending: "待处理",
  failed: "处理失败",
  unavailable: "处理状态待确认",
  已解析: "已解析",
  解析中: "解析中",
  已迁移: "已迁移",
  迁移中: "迁移中",
  待处理: "待处理",
  处理失败: "处理失败",
};

// Exported: displayLabels.ts shares these tables (cluster LE-06 / FE-08) instead of keeping a
// second byte-identical copy. Its display functions stay separate because their fallback text
// for unrecognized values differs from the ones below — see the comment there.
export const ARTIFACT_TYPE_LABELS: Record<string, string> = {
  research_snapshot: "研究摘要",
  asset_digest: "素材摘要",
  decision_brief: "决策简报",
  creation_document: "创作文档",
  publishing_package: "发布包",
  review_report: "复盘报告",
  project_summary: "项目摘要",
};

export const BODY_AUTHORITY_LABELS: Record<string, string> = {
  internal: "网页内容",
  lark: "机构云文档",
};

export const SYNC_STATUS_LABELS: Record<string, string> = {
  not_applicable: "无需同步",
  pending: "等待同步",
  synced: "已同步",
  conflict: "需要处理冲突",
  failed: "同步失败",
};

function label(value: string | null | undefined, labels: Record<string, string>, fallback: string): string {
  const normalized = value?.trim().toLowerCase();
  return normalized ? labels[normalized] ?? fallback : fallback;
}

export function trackStatusDisplayLabel(value: string | null | undefined): string {
  return label(value, TRACK_STATUS_LABELS, "状态待确认");
}

export function operationalStatusDisplayLabel(value: string | null | undefined): string {
  return label(value, OPERATIONAL_STATUS_LABELS, "运营状态未记录");
}

export function ownedAccountDataSourceDisplayLabel(value: string | null | undefined): string {
  return label(value, OWNED_ACCOUNT_DATA_SOURCE_LABELS, "资料来源未记录");
}

export function creatorRoleDisplayLabel(value: string | null | undefined): string {
  return label(value, CREATOR_ROLE_LABELS, "账号角色待确认");
}

export function relationshipRoleDisplayLabel(value: string | null | undefined): string {
  return label(value, RELATIONSHIP_ROLE_LABELS, "未设置赛道角色");
}

export function formatFitScore(value: number): string {
  if (!Number.isFinite(value) || value < 0 || value > 100) return "匹配度不可用";
  return `匹配度 ${Math.round(value)}%`;
}

export function relationshipStatusDisplayLabel(value: string | null | undefined): string {
  return label(value, RELATIONSHIP_STATUS_LABELS, "关系状态待确认");
}

export function inviteStatusDisplayLabel(value: string | null | undefined): string {
  return label(value, INVITE_STATUS_LABELS, "邀请状态待确认");
}

export function qualityDisplayLabel(value: string | null | undefined): string {
  return label(value, QUALITY_LABELS, "证据状态待确认");
}

export function mediaTypeDisplayLabel(value: string | null | undefined): string {
  return label(value, MEDIA_TYPE_LABELS, "其他素材类型");
}

export function materialStatusDisplayLabel(value: string | null | undefined): string {
  return label(value, MATERIAL_STATUS_LABELS, "素材处理状态待确认");
}

export function artifactTypeDisplayLabel(value: string | null | undefined): string {
  return label(value, ARTIFACT_TYPE_LABELS, "其他产物");
}

export function bodyAuthorityDisplayLabel(value: string | null | undefined): string {
  return label(value, BODY_AUTHORITY_LABELS, "内容来源待确认");
}

export function syncStatusDisplayLabel(value: string | null | undefined): string {
  return label(value, SYNC_STATUS_LABELS, "同步状态待确认");
}
