import { dashboardSchema, type DashboardData } from '../schemas/dashboardSchema'

export async function loadDashboardData(): Promise<DashboardData> {
  const response = await fetch(`${import.meta.env.BASE_URL}data/openclaw-bot-center.generated.json`, {
    cache: 'no-cache',
  })

  if (!response.ok) {
    throw new Error(`数据读取失败：${response.status} ${response.statusText}`)
  }

  const json = await response.json()
  return dashboardSchema.parse(json)
}
