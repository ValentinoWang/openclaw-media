import { type ReactNode } from 'react'
import {
  ArrowRight,
  BarChart3,
  Bot,
  FileSearch,
  Flame,
  Images,
  Lightbulb,
  MessageCircle,
  Radar,
  Search,
  Sparkles,
  Target,
  TrendingUp,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { useMediaWeb } from '../MediaWebWorkspace'
import styles from './DeskPage.module.css'

const deskModules = [
  {
    tone: 'research',
    icon: Radar,
    kicker: 'MONITOR',
    title: '热榜与竞品监控',
    description: '按平台、关键词、时间和标签发现候选，再回读真实作品页核验事实。',
    action: '开始调研',
    capabilityId: 'external_research_brief',
  },
  {
    tone: 'evidence',
    icon: FileSearch,
    kicker: 'DECONSTRUCT',
    title: '爆款证据拆解',
    description: '下载原视频或原图，基于关键帧、字幕、口播和评论完成结构化拆解。',
    action: '导入素材',
    capabilityId: 'source_asset_intake',
  },
  {
    tone: 'decision',
    icon: Lightbulb,
    kicker: 'DECIDE',
    title: '选题与创作咨询',
    description: '结合账号画像、活动候选、爆款样本和历史复盘，输出可执行方向。',
    action: '发起咨询',
    capabilityId: 'selfmedia_creation',
  },
  {
    tone: 'growth',
    icon: TrendingUp,
    kicker: 'LEARN',
    title: '发布复盘与账号学习',
    description: '让真实发布数据进入下一轮脚本、分镜和内容策略，而不是停在报告里。',
    action: '记录复盘',
    capabilityId: 'post_review_signal',
  },
] as const

export default function DeskPage() {
  const { openWorkspace } = useMediaWeb()
  return (
    <main className="mg-page" data-accent="desk" data-page-ownership="personal">
      <section className="mg-hero" data-page-prelude>
        <div>
          <span className="mg-eyebrow"><Sparkles size={15} />CONTENT INTELLIGENCE DESK</span>
          <h1>内容情报工作台</h1>
          <p className="mg-hero-lead">包含热榜监控、证据拆解、选题咨询和发布复盘。</p>
          <div className="mg-hero-actions">
            <button className="mg-btn mg-btn-primary" type="button" onClick={() => openWorkspace()}><Bot size={17} />开始一次研究任务</button>
            <Link className="mg-btn mg-btn-soft" to="/assets"><Images size={17} />查看素材证据</Link>
          </div>
        </div>
        <div className={`mg-hero-signal ${styles.signalCard}`}>
          <span>Desk 的交付标准</span>
          <strong>可回查</strong>
          <p>每个建议都能回到来源、素材、指标或人工确认，不把推测包装成事实。</p>
        </div>
      </section>

      <section className={styles.pipeline} aria-label="内容情报工作流">
        <PipelineStep icon={<Search size={18} />} label="发现" detail="热榜、关键词、账号" />
        <ArrowRight size={16} />
        <PipelineStep icon={<Flame size={18} />} label="拆解" detail="钩子、节奏、视觉" />
        <ArrowRight size={16} />
        <PipelineStep icon={<Target size={18} />} label="决策" detail="人群、痛点、角度" />
        <ArrowRight size={16} />
        <PipelineStep icon={<BarChart3 size={18} />} label="复盘" detail="指标、模式、下一步" />
      </section>

      <section className={styles.moduleGrid}>
        {deskModules.map(({ tone, icon: Icon, kicker, title, description, action, capabilityId }) => (
          <article className={styles.moduleCard} data-tone={tone} key={title}>
            <header><span><Icon size={21} /></span><small>{kicker}</small></header>
            <h2>{title}</h2>
            <p>{description}</p>
            <button className="mg-btn mg-btn-ghost" type="button" onClick={() => openWorkspace({ capabilityId, variantId: 'default' })}>{action}<ArrowRight size={15} /></button>
          </article>
        ))}
      </section>

      <div className={styles.layout}>
        <section className="mg-panel">
          <header className="mg-panel-head"><div><span>研究原则</span><h2>什么才算可以进入创作的结论</h2></div></header>
          <div className={styles.principleGrid}>
            <Principle icon={<FileSearch size={19} />} title="来源真实" detail="原作品、发布时间、互动数据与媒体文件能够重新回查。" />
            <Principle icon={<MessageCircle size={19} />} title="需求有原话" detail="评论需求和用户痛点保留上下文，不只留下模型摘要。" />
            <Principle icon={<Target size={19} />} title="建议可执行" detail="明确目标人群、单一问题、内容角度和下一步动作。" />
            <Principle icon={<TrendingUp size={19} />} title="结果能回流" detail="发布后的真实表现会更新账号模式与下一轮决策。" />
          </div>
        </section>

        <aside className={`mg-panel ${styles.linkPanel}`}>
          <header className="mg-panel-head"><div><span>现有工作区</span><h2>继续深入</h2></div></header>
          <nav>
            <DeskLink to="/assets" icon={<Images size={18} />} title="素材与证据" detail="查看来源、拆解和原始附件" />
            <DeskLink to="/decisions" icon={<Lightbulb size={18} />} title="选题与决策" detail="核对证据、候选与人工状态" />
            <DeskLink to="/reviews" icon={<TrendingUp size={18} />} title="复盘洞察" detail="记录指标并沉淀账号经验" />
            <DeskLink to="/studio" icon={<Sparkles size={18} />} title="进入 Studio" detail="把研究结论变成脚本和分镜" />
          </nav>
        </aside>
      </div>
    </main>
  )
}

function PipelineStep({ icon, label, detail }: { icon: ReactNode; label: string; detail: string }) {
  return <article><span>{icon}</span><div><strong>{label}</strong><small>{detail}</small></div></article>
}

function Principle({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return <article><span>{icon}</span><div><strong>{title}</strong><p>{detail}</p></div></article>
}

function DeskLink({ to, icon, title, detail }: { to: string; icon: ReactNode; title: string; detail: string }) {
  return <Link to={to}>{icon}<span><strong>{title}</strong><small>{detail}</small></span><ArrowRight size={15} /></Link>
}
