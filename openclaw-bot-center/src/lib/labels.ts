import type { BotId, Capability, Flow } from '../schemas/dashboardSchema'

export const botNames: Record<BotId, string> = {
  media: 'Media',
  daily: 'Daily',
  knowledge: 'Knowledge',
  social: 'Social',
  deepmath: 'DeepMath',
}

export const botChineseNames: Record<BotId, string> = {
  media: '内容创作',
  daily: '日程执行',
  knowledge: '知识整理',
  social: '社交人脉',
  deepmath: 'DeepMath 思考',
}

export const taskGroupNames: Record<string, string> = {
  content: '内容生产',
  daily: '日程执行',
  knowledge: '知识整理',
  social: '社交人脉',
  deepmath: 'DeepMath 思考',
}

export const categoryNames: Record<Capability['category'], string> = {
  creation: '创作',
  material: '素材',
  review: '复盘验收',
  daily: '日常',
  wardrobe: '衣橱',
  development: '开发',
  knowledge: '知识',
  research: '调研',
  social: '社交',
  business: '商务',
  entity: '实体模型',
  system: '系统',
}

export const typeNames: Record<Capability['type'], string> = {
  main: '主能力',
  collaboration: '协作能力',
  common: '通用能力',
  boundary: '边界能力',
}

export const availabilityNames: Record<Capability['botAvailability'][BotId], string> = {
  primary: '主能力',
  visible: '可见',
  not_recommended: '不建议',
  hidden: '不可见',
}

export const flowOwnerNames: Record<Flow['stages'][number]['owner'], string> = {
  cloud: '腾讯云处理',
  mac: 'Mac 侧处理',
  human: '人工处理',
  mixed: '协同处理',
  storage: '文件 / 产物',
}

// implementationStatus → Chinese (cluster LE-12). "not_implemented" and "external" already agree
// everywhere ("规划中" / "既有链路"); "implemented" does not — App.tsx's primary capability list
// says "可用" (a plain end-user affordance), while the maintainer-facing map pages (business map,
// capability tree, flow map) say "已落地" (an implementation-status framing). That is a real,
// already-shipped wording split rather than an accidental copy/paste drift, so both spellings are
// kept as named exports instead of one silently overwriting the other. Which one is "correct" is a
// product-wording decision, not a dedup one.
export const implementationStatusNames: Record<Capability['implementationStatus'], string> = {
  implemented: '已落地',
  not_implemented: '规划中',
  external: '既有链路',
}

export const implementationStatusNamesPrimary: Record<Capability['implementationStatus'], string> = {
  ...implementationStatusNames,
  implemented: '可用',
}

export const implementationStatusHelp: Record<Capability['implementationStatus'], string> = {
  implemented: '已实装，可直接发送到对应 Bot 使用。',
  not_implemented: '规划中。复制模板发送后会收到待人工处理回执，不代表系统故障。',
  external: '由既有创作、复盘或其他 canonical 链路执行。',
}
