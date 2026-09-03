import { useMemo } from 'react'
import {
  AlertCircle,
  ArrowRight,
  BriefcaseBusiness,
  CheckCircle2,
  CircleDot,
  Clock3,
  ExternalLink,
  FilePenLine,
  PackageCheck,
  Plus,
  RefreshCw,
  Send,
  Sparkles,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { useMediaWeb } from '../MediaWebWorkspace'
import type { MediaWebTask } from '../mediaWebApi'
import { runStatusLabel, runStatusTone } from '../statusPresentation'
import { formatDate } from '../ui/ordinaryPagePrimitives'
import { Metric } from '../ui/Metric'
import { SurfaceState } from '../ui/SurfaceState'
import styles from './CampaignsPage.module.css'

const stages = [
  { label: 'Brief', detail: '品牌要求与活动资料', icon: BriefcaseBusiness },
  { label: '初稿', detail: '脚本、分镜与拍摄单', icon: FilePenLine },
  { label: '审核', detail: '品牌意见与人工确认', icon: AlertCircle },
  { label: '返修', detail: '局部修改与版本留痕', icon: RefreshCw },
  { label: '交付', detail: '发布包与交付凭证', icon: PackageCheck },
]

export default function CampaignsPage() {
  const { tasks, openWorkspace } = useMediaWeb()
  const campaignTasks = useMemo(
    () => tasks.filter((task) => task.capabilityId === 'commercial_delivery_draft').sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt)),
    [tasks],
  )
  const active = campaignTasks.filter((task) => !task.terminal)
  const waiting = campaignTasks.filter((task) => ['awaiting_confirmation', 'pending_manual'].includes(task.status))
  const completed = campaignTasks.filter((task) => task.terminal && task.status === 'succeeded')

  return (
    <main className="mg-page" data-accent="campaign" data-page-ownership="personal">
      <section className={`mg-hero ${styles.hero}`} data-page-prelude>
        <div>
          <span className="mg-eyebrow"><Sparkles size={15} />CAMPAIGN DELIVERY</span>
          <h1>活动与商单履约</h1>
          <p className="mg-hero-lead">记录商单的 Brief、脚本、分镜、返修和发布包。</p>
          <div className="mg-hero-actions">
            <button className="mg-btn mg-btn-primary" type="button" onClick={() => openWorkspace({ capabilityId: 'commercial_delivery_draft', variantId: 'default' })}><Plus size={17} />新建商单项目</button>
            <Link className="mg-btn mg-btn-soft" to="/business"><BriefcaseBusiness size={17} />查看商务机会</Link>
          </div>
        </div>
        <div className={`mg-hero-signal ${styles.heroCard}`}>
          <span>当前履约</span>
          <strong>{active.length}</strong>
          <p>{waiting.length ? `${waiting.length} 个项目等待审核或补充` : '没有待人工确认的交付任务'}</p>
          <small>以真实任务和交付链接为准</small>
        </div>
      </section>

      <section className={styles.stageRail} aria-label="商单履约阶段">
        {stages.map(({ label, detail, icon: Icon }, index) => (
          <article key={label}>
            <span><Icon size={18} /></span>
            <div><strong>{label}</strong><small>{detail}</small></div>
            {index < stages.length - 1 ? <ArrowRight size={15} aria-hidden="true" /> : null}
          </article>
        ))}
      </section>

      <section className={styles.metricGrid}>
        <Metric variant="card" className={styles.metric} icon={<Clock3 size={18} />} label="进行中" value={active.length} detail="等待生成、审核或交付" />
        <Metric variant="card" className={styles.metric} icon={<AlertCircle size={18} />} label="待人工处理" value={waiting.length} detail="审核、补充与返修" />
        <Metric variant="card" className={styles.metric} icon={<CheckCircle2 size={18} />} label="已完成" value={completed.length} detail="已有可回查交付结果" />
        <Metric variant="card" className={styles.metric} icon={<PackageCheck size={18} />} label="全部商单" value={campaignTasks.length} detail="当前账户任务记录" />
      </section>

      <div className={styles.layout}>
        <section className="mg-panel">
          <header className="mg-panel-head"><div><span>交付项目</span><h2>最近商单</h2></div><button className="mg-btn mg-btn-soft" type="button" onClick={() => openWorkspace({ capabilityId: 'commercial_delivery_draft', variantId: 'default' })}><Plus size={15} />新建</button></header>
          {campaignTasks.length ? (
            <div className={styles.campaignList}>
              {campaignTasks.map((task) => <CampaignCard key={task.taskId} task={task} onOpen={() => openWorkspace()} />)}
            </div>
          ) : (
            <SurfaceState
              kind="empty"
              title="还没有商单交付项目"
              detail="导入品牌或活动 Brief 后，系统会生成可编辑初稿、分镜和交付文档。"
              action={<button className="mg-btn mg-btn-primary" type="button" onClick={() => openWorkspace({ capabilityId: 'commercial_delivery_draft', variantId: 'default' })}>创建第一个商单</button>}
            />
          )}
        </section>

        <aside className="mg-panel">
          <header className="mg-panel-head"><div><span>履约标准</span><h2>一份商单必须闭合什么</h2></div></header>
          <div className={styles.checkList}>
            <CheckItem title="原始 Brief 可回查" detail="品牌、产品、平台、交付时间和禁区不靠模型猜测。" />
            <CheckItem title="脚本和分镜可以继续改" detail="人工修改优先，返修产生新版本，不覆盖已确认稿。" />
            <CheckItem title="审核意见有明确位置" detail="记录改哪里、改成什么、为什么以及由谁确认。" />
            <CheckItem title="最终交付有真实链接" detail="飞书文档、发布包和结果链接统一回到同一商单。" />
          </div>
          <div className={styles.callout}>
            <Send size={19} />
            <div><strong>下一步产品重点</strong><p>把品牌批注、局部 Patch、版本 Diff 与发布回执放到同一个项目详情页。</p></div>
          </div>
        </aside>
      </div>
    </main>
  )
}

function CampaignCard({ task, onOpen }: { task: MediaWebTask; onOpen: () => void }) {
  const tone = runStatusTone(task.status)
  const links = task.result?.links ?? []
  return (
    <article className={styles.campaignCard}>
      <header>
        <div className={styles.campaignIdentity}><span><CircleDot size={10} />商单交付</span><h3>{task.summary || '未命名商单项目'}</h3><code>{task.taskId}</code></div>
        <span className="mg-badge" data-tone={tone}>{runStatusLabel(task.status)}</span>
      </header>
      <div className={styles.progressRow}><div><span style={{ width: `${task.progress}%` }} /></div><strong>{task.progress}%</strong></div>
      <footer>
        <span>更新于 {formatDate(task.updatedAt)}</span>
        <div className={styles.linkRow}>
          {links.slice(0, 2).map((link) => <a key={`${link.label}-${link.url}`} href={link.url} target="_blank" rel="noreferrer"><ExternalLink size={13} />{link.label}</a>)}
          <button type="button" onClick={onOpen}>查看任务<ArrowRight size={14} /></button>
        </div>
      </footer>
    </article>
  )
}

function CheckItem({ title, detail }: { title: string; detail: string }) {
  return <div className={styles.checkItem}><CheckCircle2 size={18} /><div><strong>{title}</strong><p>{detail}</p></div></div>
}
