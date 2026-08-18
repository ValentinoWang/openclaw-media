import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { dashboardSchema } from '../../src/schemas/dashboardSchema'

const dataPath = resolve('public/data/openclaw-bot-center.generated.json')
const flowPagePath = resolve('src/pages/FlowMapPage.tsx')
const appPath = resolve('src/App.tsx')
const forbidden = [
  'OTIO',
  'Kdenlive',
  'EDL',
  '剪映',
  'draft_content',
  '/Users/',
  '/home/',
  'task_',
  'change_request',
  'project_revision',
  'editor_backend',
  'Traceback',
  'error_code',
]

function fail(messages: string[]) {
  console.error(messages.map((message) => `- ${message}`).join('\n'))
  process.exit(1)
}

const parsed = dashboardSchema.safeParse(JSON.parse(readFileSync(dataPath, 'utf-8')))
if (!parsed.success) {
  fail([`Bot Center generated data does not match the schema: ${parsed.error.message}`])
}

const data = parsed.data
const errors: string[] = []
const contentFlow = data.flows.find((flow) => flow.id === 'cloud-mac-materials')
if (!contentFlow) {
  errors.push('内容生产流程不存在')
} else {
  const contentText = JSON.stringify(contentFlow)
  for (const term of forbidden) {
    if (contentText.includes(term)) errors.push(`内容生产流程暴露了不应给运营看的内容：${term}`)
  }
  const planStage = contentFlow.stages.find((stage) => stage.id === 'creative-assembly')
  const editStage = contentFlow.stages.find((stage) => stage.id === 'editing-packaging')
  if (planStage?.title !== '生成剪辑方案') errors.push('第 5 步必须显示为“生成剪辑方案”')
  if (editStage?.title !== '做包装和人工精剪') errors.push('第 6 步必须显示为“做包装和人工精剪”')
  if (!planStage?.outputs.includes('标准剪辑交接包或可编辑时间线')) {
    errors.push('第 5 步必须明确展示两种剪辑交接方式')
  }
}

const dashboard = data.contentOsProjectDashboard
if (dashboard.title !== '项目详情') errors.push('项目详情标题缺失')
if (dashboard.modificationEntry.label !== '在 Media Bot 对话中提交修改') errors.push('修改入口文案错误')
if (dashboard.modificationEntry.url !== '#/bots/media') errors.push('修改入口没有指向 Media Bot')
if (!dashboard.modificationEntry.instruction.includes('【修改】修改项目')) errors.push('修改入口缺少实际发送方式')
for (const project of dashboard.projects) {
  const visible = [
    project.title,
    project.stage,
    project.revision,
    project.editingMethod,
    project.owner,
    project.nextAction,
    project.blockedReason,
  ].join('\n')
  for (const term of forbidden) {
    if (visible.includes(term)) errors.push(`项目详情暴露了不应给运营看的内容：${term}`)
  }
}

const pageSource = readFileSync(flowPagePath, 'utf-8')
for (const label of ['项目阶段', '当前版本', '剪辑方式', '负责人', '下一步', '阻塞原因', '提交修改']) {
  if (!pageSource.includes(label)) errors.push(`项目详情页面缺少字段：${label}`)
}
if (!pageSource.includes('ContentOsProjectDashboardPanel')) {
  errors.push('流程页面没有渲染项目详情面板')
}

const appSource = readFileSync(appPath, 'utf-8')
if (appSource.includes('SystemMaintenancePanel') || appSource.includes('compact-archetype-layout')) {
  errors.push('System/Maintenance 仍保留独立页面原型')
}
if (!appSource.includes("archetype === 'creation_handoff' || archetype === 'system_maintenance'")) {
  errors.push('System/Maintenance 没有接入统一交付工作台')
}

if (errors.length > 0) fail(errors)
console.log(`Content OS v0.2 presentation checks passed for ${dashboard.projects.length} project(s).`)
