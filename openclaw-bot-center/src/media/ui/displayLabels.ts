import type { PipelineSummary } from "../generatedProductContract";

export const DISPLAY_LABELS = {
  commercialDeliveryRecord: "商单交付记录",
  dataVersion: "数据版本",
  trackCreatorMembership: "账号与赛道关系",
  creatorProfile: "对标账号资料",
  standardSummary: "标准汇总",
  publishedRecord: "服务端正式发布记录",
} as const;

const PROJECT_STAGE_LABELS: Record<string, string> = {
  research: "研究",
  assets: "素材整理",
  decision: "选题决策",
  creation: "内容创作",
  publishing: "发布准备",
  review: "复盘增长",
};
const PROJECT_STATUS_LABELS: Record<string, string> = {
  active: "进行中",
  draft: "草稿",
  paused: "已暂停",
  completed: "已完成",
  archived: "已归档",
  failed: "处理失败",
};
const WORKSPACE_MODE_LABELS: Record<string, string> = {
  personal_web: "个人工作区",
  organization_lark: "机构工作区",
};
const ARTIFACT_TYPE_LABELS: Record<string, string> = {
  research_snapshot: "研究摘要",
  asset_digest: "素材摘要",
  decision_brief: "决策简报",
  creation_document: "创作文档",
  publishing_package: "发布包",
  review_report: "复盘报告",
  project_summary: "项目摘要",
};
const BODY_AUTHORITY_LABELS: Record<string, string> = {
  internal: "网页内容",
  lark: "机构云文档",
};
const SYNC_STATUS_LABELS: Record<string, string> = {
  not_applicable: "无需同步",
  pending: "等待同步",
  synced: "已同步",
  conflict: "需要处理冲突",
  failed: "同步失败",
};
const ACTION_LABELS: Record<string, string> = {
  view: "查看",
  open_organization_document: "打开机构云文档",
  regenerate: "重新生成",
  resolve_sync: "处理同步问题",
};

export function projectStageDisplayLabel(value: string): string {
  return PROJECT_STAGE_LABELS[value] || "其他阶段";
}
export function projectStatusDisplayLabel(value: string): string {
  return PROJECT_STATUS_LABELS[value] || "其他状态";
}
export function workspaceModeDisplayLabel(value: string): string {
  return WORKSPACE_MODE_LABELS[value] || "工作区";
}
export function artifactTypeDisplayLabel(value: string): string {
  return ARTIFACT_TYPE_LABELS[value] || "其他产物";
}
export function bodyAuthorityDisplayLabel(value: string): string {
  return BODY_AUTHORITY_LABELS[value] || "内容来源";
}
export function syncStatusDisplayLabel(value: string): string {
  return SYNC_STATUS_LABELS[value] || "同步状态未知";
}
export function actionDisplayLabel(value: string): string {
  return ACTION_LABELS[value] || "可用操作";
}

const PIPELINE_LABELS: Record<string, { label: string; description: string }> = {
  "media.edit.handoff.v1": { label: "内容编辑交接", description: "把内容编辑任务交给本端客户端继续处理。" },
  "media.edit.revise.v1": { label: "内容修改确认", description: "根据确认意见整理并更新内容。" },
  "media.edit.timeline.v1": { label: "内容时间线编辑", description: "整理内容的时间线与编辑节点。" },
  "media.material.match.v1": { label: "素材匹配", description: "为当前任务匹配可用素材。" },
  "media.material.organize.v1": { label: "素材整理", description: "整理素材并建立可追踪的内容关系。" },
  "media.output.review.v1": { label: "内容产物复核", description: "检查内容产物是否满足交付要求。" },
  "media.project.prepare.v1": { label: "项目准备", description: "准备项目所需的素材、配置与执行信息。" },
  "media.rhythm.review.v1": { label: "节奏复盘", description: "复盘内容节奏并记录后续调整方向。" },
  "media.semantic.review.v1": { label: "语义复核", description: "检查内容表达、语义和上下文一致性。" },
};

export function pipelineDisplayLabel(pipeline: PipelineSummary): string {
  const known = PIPELINE_LABELS[pipeline.pipeline_id]?.label;
  if (known) return known;
  return "其他流程";
}

export function pipelineDisplayDescription(pipeline: PipelineSummary): string {
  return PIPELINE_LABELS[pipeline.pipeline_id]?.description || "已安装，可用于本地运行。";
}
