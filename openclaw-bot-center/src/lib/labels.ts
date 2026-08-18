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
