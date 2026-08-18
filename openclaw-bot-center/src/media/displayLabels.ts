import type { PipelineSummary } from "../generatedProductContract";

export const DISPLAY_LABELS = {
  trackCreatorMembership: "账号与赛道关系",
  creatorProfile: "对标账号资料",
  standardSummary: "标准汇总",
  publishedRecord: "服务端正式发布记录",
} as const;

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
  return /[\u4e00-\u9fff]/.test(pipeline.display_name) ? pipeline.display_name : "未命名流程";
}

export function pipelineDisplayDescription(pipeline: PipelineSummary): string {
  return PIPELINE_LABELS[pipeline.pipeline_id]?.description || "已安装，可用于本地运行。";
}
