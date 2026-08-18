import type { CapabilityField } from "../../schemas/capabilityCatalogSchema";

const fieldLabelsByKey: Record<string, string> = {
  account_id: "账号编号",
  artifact_id: "成果编号",
  creation_run_id: "创作运行编号",
  creator_id: "博主编号",
  draft_id: "草稿编号",
  idempotency_key: "重复提交保护",
  idempotency_receipt: "重复提交保护",
  idempotency_receipt_id: "重复提交保护",
  run_id: "运行编号",
  source_url: "素材链接",
  sub_agent_count: "协作助手数量",
  sub_agents: "协作助手",
  subagent_count: "协作助手数量",
  subagents: "协作助手",
  track_id: "赛道编号",
};

const helpTextByKey: Record<string, string> = {
  idempotency_key: "选填。重复操作时填写同一个编号，系统只会受理一次。",
  idempotency_receipt: "选填。重复操作时填写同一个编号，系统只会受理一次。",
  idempotency_receipt_id: "选填。重复操作时填写同一个编号，系统只会受理一次。",
  sub_agent_count: "填写参与本次任务的协作助手数量。",
  sub_agents: "选择参与本次任务的协作助手。",
  subagent_count: "填写参与本次任务的协作助手数量。",
  subagents: "选择参与本次任务的协作助手。",
};

const vocabulary: ReadonlyArray<readonly [string, string]> = [
  ["幂等号收据 ID", "重复提交保护编号"],
  ["幂等收据 ID", "重复提交保护编号"],
  ["幂等号收据", "重复提交保护"],
  ["幂等收据", "重复提交保护"],
  ["幂等键", "重复提交保护编号"],
  ["Idempotency", "重复提交保护"],
  ["idempotency", "重复提交保护"],
  ["Sub-agents", "协作助手"],
  ["SubAgents", "协作助手"],
  ["Subagents", "协作助手"],
  ["subAgents", "协作助手"],
  ["sub-agents", "协作助手"],
  ["subagents", "协作助手"],
];

const systemManagedFieldPattern = /(?:^|_)idempotency(?:_|$)/i;

export function isSystemManagedCapabilityField(field: CapabilityField) {
  return (
    systemManagedFieldPattern.test(field.key) ||
    [field.sourceLabel, field.label, field.placeholder, field.helpText].some(
      (value) => /幂等|idempotency/i.test(value),
    )
  );
}

export function presentCapabilityText(value: string) {
  const direct = fieldLabelsByKey[value];
  if (direct) return direct;
  return vocabulary.reduce(
    (text, [source, target]) => text.replaceAll(source, target),
    value.replaceAll("_", " "),
  );
}

export function presentCapabilityFieldLabel(field: CapabilityField) {
  return fieldLabelsByKey[field.key] ?? presentCapabilityText(field.label);
}

export function presentCapabilityFieldHelp(field: CapabilityField) {
  return helpTextByKey[field.key] ?? presentCapabilityText(field.helpText);
}
