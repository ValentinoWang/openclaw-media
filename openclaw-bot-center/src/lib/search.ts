import Fuse from 'fuse.js'
import type { Bot, Capability, DashboardData, Flow, LinkItem, Task } from '../schemas/dashboardSchema'

export type SearchResult =
  | { kind: 'Bot'; title: string; subtitle: string; href: string; item: Bot }
  | { kind: '能力'; title: string; subtitle: string; href: string; item: Capability }
  | { kind: '入口'; title: string; subtitle: string; href: string; item: Capability }
  | { kind: '任务'; title: string; subtitle: string; href: string; item: Task }
  | { kind: '流程'; title: string; subtitle: string; href: string; item: Flow }
  | { kind: '跳转'; title: string; subtitle: string; href: string; item: LinkItem }

type SearchRecord = {
  kind: SearchResult['kind']
  title: string
  subtitle: string
  href: string
  text: string
  item: SearchResult['item']
}

export function buildSearch(data: DashboardData) {
  const records: SearchRecord[] = [
    ...data.bots.map((bot) => ({
      kind: 'Bot' as const,
      title: bot.name,
      subtitle: bot.title,
      href: `#/bots/${bot.id}`,
      text: `${bot.name} ${bot.title} ${bot.description}`,
      item: bot,
    })),
    ...data.capabilities.map((capability) => ({
      kind: '能力' as const,
      title: capability.rawLabel,
      subtitle: capability.title,
      href: `#/capabilities/detail/${capability.id}`,
      text: [
        capability.rawLabel,
        capability.title,
        capability.description,
        capability.aliases.join(' '),
        capability.keywords.join(' '),
        capability.taskGroups.join(' '),
        capability.defaultInputTemplate,
        capability.quickCopyTemplates.map((template) => `${template.title} ${template.description} ${template.body}`).join(' '),
        capability.displayProjection.operatorSummary,
        capability.displayProjection.requiredInputs.join(' '),
        capability.displayProjection.outputSummary.join(' '),
      ].join(' '),
      item: capability,
    })),
    ...data.capabilities.flatMap((capability) => (
      capability.entryTree?.children.map((entry) => ({
        kind: '入口' as const,
        title: entry.trigger,
        subtitle: `${capability.rawLabel} / ${entry.displayName}`,
        href: `#/capabilities/detail/${capability.id}?entry=${encodeURIComponent(entry.id)}`,
        text: [
          entry.trigger,
          entry.displayName,
          entry.purpose,
          capability.rawLabel,
          capability.title,
          entry.inputContract.requiredFields.join(' '),
          entry.inputContract.templates.map((template) => `${template.title} ${template.description} ${template.body}`).join(' '),
          entry.outputContract.userReplySections.join(' '),
          entry.outputContract.artifacts.join(' '),
        ].join(' '),
        item: capability,
      })) ?? []
    )),
    ...data.tasks.map((task) => ({
      kind: '任务' as const,
      title: task.title,
      subtitle: task.description,
      href: `#/tasks/${task.id}`,
      text: `${task.title} ${task.description} ${task.group}`,
      item: task,
    })),
    ...data.flows.map((flow) => ({
      kind: '流程' as const,
      title: flow.title,
      subtitle: flow.description,
      href: `#/flows/${flow.id}`,
      text: [
        flow.title,
        flow.description,
        flow.sourceDoc,
        ...flow.stages.flatMap((stage) => [
          stage.title,
          stage.summary,
          stage.owner,
          stage.inputs.join(' '),
          stage.outputs.join(' '),
          stage.boundaries.join(' '),
        ]),
      ].join(' '),
      item: flow,
    })),
    ...data.links.map((link) => ({
      kind: '跳转' as const,
      title: link.title,
      subtitle: link.description,
      href: link.url,
      text: `${link.title} ${link.description} ${link.group}`,
      item: link,
    })),
  ]

  const fuse = new Fuse(records, {
    keys: [
      { name: 'title', weight: 0.45 },
      { name: 'subtitle', weight: 0.25 },
      { name: 'text', weight: 0.3 },
    ],
    threshold: 0.32,
    ignoreLocation: true,
    includeScore: true,
  })

  return (query: string): SearchResult[] => {
    const trimmed = query.trim()
    if (!trimmed) {
      return []
    }
    const bracketed = trimmed.startsWith('【') ? trimmed : `【${trimmed}】`
    const tokenMatches = records
      .filter((record) => recordMatchesQuery(record, trimmed))
      .map((record) => ({ item: record, score: -0.1 }))
    const merged = new Map<string, { item: SearchRecord; score?: number }>()
    for (const result of tokenMatches) {
      merged.set(`${result.item.kind}-${result.item.href}`, result)
    }
    for (const result of fuse.search(trimmed, { limit: 18 })) {
      const key = `${result.item.kind}-${result.item.href}`
      if (!merged.has(key)) {
        merged.set(key, { item: result.item, score: result.score })
      }
    }
    return Array.from(merged.values())
      .sort((left, right) => {
        const leftRank = searchRank(left.item, bracketed, trimmed)
        const rightRank = searchRank(right.item, bracketed, trimmed)
        if (leftRank !== rightRank) return leftRank - rightRank
        return (left.score ?? 0) - (right.score ?? 0)
      })
      .slice(0, 12)
      .map((result) => {
      const record = result.item
      return {
        kind: record.kind,
        title: record.title,
        subtitle: record.subtitle,
        href: record.href,
        item: record.item,
      } as SearchResult
    })
  }
}

function searchRank(record: SearchRecord, bracketedQuery: string, rawQuery: string) {
  const normalizedTitle = normalizeSearchText(record.title)
  const queryTitleTokens = queryTokens(rawQuery)
  const titleMatchesToken = queryTitleTokens.some((token) => token && normalizedTitle.includes(token))
  if (record.kind === '入口' && (record.title === bracketedQuery || record.title.includes(rawQuery) || titleMatchesToken)) {
    return 0
  }
  if (record.kind === '能力' && (record.title === bracketedQuery || titleMatchesToken)) {
    return 1
  }
  if (record.kind === '入口') {
    return 2
  }
  return 3
}

function recordMatchesQuery(record: SearchRecord, query: string) {
  const tokens = queryTokens(query)
  if (!tokens.length) return false
  const normalized = normalizeSearchText(`${record.title} ${record.subtitle} ${record.text}`)
  return tokens.every((token) => normalized.includes(token))
}

function queryTokens(query: string) {
  const normalized = normalizeSearchText(query)
  if (!normalized) return []
  const dictionary = [
    'sourceasset',
    '素材',
    '小红书',
    '抖音',
    '爆款',
    '视频',
    '图片',
    '活动',
    '转写',
    '拆解',
    '素材',
    '创作',
    '选题',
    '调研',
    '润色',
    '检查',
    '发布',
    '复盘',
    '今日',
    '日记',
    '周记',
    '待办',
    '日程',
    '开发',
  ].map(normalizeSearchText)
  const tokens = dictionary.filter((term) => term && normalized.includes(term))
  if (tokens.length) return Array.from(new Set(tokens))
  return [normalized]
}

function normalizeSearchText(text: string) {
  return text
    .toLowerCase()
    .replace(/[【】\s/|,，。.:：;；、>_\-—()（）[\]{}]/g, '')
}
