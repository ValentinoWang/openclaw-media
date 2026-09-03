import { useState, type ReactNode } from 'react'
import {
  AlertCircle,
  ArrowRight,
  BadgeDollarSign,
  BriefcaseBusiness,
  CircleDollarSign,
  LoaderCircle,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Users,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { useMediaWeb } from '../MediaWebWorkspace'
import { callBusinessOperation } from '../generatedBusinessPagesContract'
import { PlatformIdentity } from '../ui/PlatformIdentity'
import { describeBusinessError, toResourceState } from '../ui/businessOperationError'
import { useResource, type LoadState } from '../ui/loadState'
import { SurfaceState } from '../ui/SurfaceState'
import { Metric } from '../ui/Metric'
import { formatDate } from '../ui/ordinaryPagePrimitives'
import { authorizationScopeDisplayLabel } from '../ui/ordinaryDataLabels'
import { businessStatusTone } from '../statusPresentation'
import styles from './BusinessPage.module.css'

type BusinessOpportunity = {
  publicOpportunityId: string
  brand: string
  product: string
  platform: string
  contentType: string
  validFrom: string | null
  validUntil: string | null
  authorizationScope: string
  status: string
}

type OpportunityResponse = {
  revision: number
  items: BusinessOpportunity[]
  nextCursor: string | null
}

export default function BusinessPage() {
  const { openWorkspace } = useMediaWeb()
  const [refreshToken, setRefreshToken] = useState(0)
  const state = useResource<OpportunityResponse>(
    (signal) => callBusinessOperation<OpportunityResponse>('listBusinessOpportunities', {
      query: { pageSize: 50 },
      signal,
    }),
    toOpportunityState,
    [refreshToken],
  )

  const opportunities = state.status === 'ready' ? state.data.items : []
  const active = opportunities.filter((item) => !['completed', 'closed', 'rejected', 'expired'].includes(item.status))
  const brands = new Set(opportunities.map((item) => item.brand).filter(Boolean)).size
  const platforms = new Set(opportunities.map((item) => item.platform).filter(Boolean)).size

  return (
    <main className="mg-page" data-accent="business" data-page-ownership="personal">
      <section className={`mg-hero ${styles.hero}`} data-page-prelude>
        <div>
          <span className="mg-eyebrow"><Sparkles size={15} />CREATOR BUSINESS OS</span>
          <h1>报价、档期、权益与商机</h1>
          <p className="mg-hero-lead">账号报价和品牌商务机会分开记录，两边互相关联。</p>
          <div className="mg-hero-actions">
            <button className="mg-btn mg-btn-primary" type="button" onClick={() => openWorkspace({ capabilityId: 'commercial_delivery_draft', variantId: 'default' })}><Plus size={17} />登记商务机会</button>
            <Link className="mg-btn mg-btn-soft" to="/tracks"><Users size={17} />查看达人与账号</Link>
          </div>
        </div>
        <div className={`mg-hero-signal ${styles.heroCard}`}>
          <span>当前有效机会</span>
          {state.status === 'loading' || state.status === 'idle' ? <LoaderCircle className="spin" size={24} /> : state.status !== 'ready' ? <AlertCircle size={24} /> : <strong>{active.length}</strong>}
          <p>{brands ? `覆盖 ${brands} 个品牌、${platforms} 个平台` : '等待登记第一条真实商务机会'}</p>
          <small>不根据项目名猜测报价或授权</small>
        </div>
      </section>

      <section className={styles.metricGrid}>
        <Metric variant="card" className={styles.metric} icon={<BriefcaseBusiness size={18} />} label="全部机会" value={opportunities.length} detail="当前账户授权范围" />
        <Metric variant="card" className={styles.metric} icon={<CircleDollarSign size={18} />} label="有效机会" value={active.length} detail="仍在推进或可执行" />
        <Metric variant="card" className={styles.metric} icon={<BadgeDollarSign size={18} />} label="合作品牌" value={brands} detail="按品牌名称去重" />
        <Metric variant="card" className={styles.metric} icon={<ShieldCheck size={18} />} label="平台覆盖" value={platforms} detail="报价与权益分平台" />
      </section>

      <div className={styles.layout}>
        <section className="mg-panel">
          <header className="mg-panel-head">
            <div><span>商务机会</span><h2>品牌与项目机会</h2></div>
            <button className="mg-btn mg-btn-soft" type="button" onClick={() => setRefreshToken((value) => value + 1)}><RefreshCw size={15} />刷新</button>
          </header>
          <OpportunityCollection state={state} onRetry={() => setRefreshToken((value) => value + 1)} onRegister={() => openWorkspace({ capabilityId: 'commercial_delivery_draft', variantId: 'default' })} />
        </section>

        <aside className="mg-panel">
          <header className="mg-panel-head"><div><span>经营模型</span><h2>账号事实与项目事实分层</h2></div></header>
          <div className={styles.modelStack}>
            <ModelCard icon={<Users size={18} />} title="达人账号档案" detail="平台身份、人设、公开表达边界和账号指标。" tags={['Creator Profile', '账号证据']} />
            <ArrowRight className={styles.modelArrow} size={18} />
            <ModelCard icon={<BadgeDollarSign size={18} />} title="账号级报价" detail="图文、视频及当前报价快照，不绑定单一品牌。" tags={['报价快照', '有效时间']} />
            <ArrowRight className={styles.modelArrow} size={18} />
            <ModelCard icon={<BriefcaseBusiness size={18} />} title="项目级机会" detail="品牌、产品、档期、返点、保价与授权权益。" tags={['Business Opportunity', '履约入口']} />
          </div>
          <div className={styles.boundaryCard}>
            <ShieldCheck size={19} />
            <div><strong>事实边界</strong><p>缺少报价、档期或授权时保留为空并请求确认，不用默认值伪装成已确认事实。</p></div>
          </div>
        </aside>
      </div>
    </main>
  )
}

function OpportunityCard({ item }: { item: BusinessOpportunity }) {
  return (
    <article className={styles.opportunityCard}>
      <header>
        <div><span>{item.brand || '未记录品牌'}</span><h3>{item.product || '未记录产品'}</h3></div>
        <StatusBadge status={item.status} />
      </header>
      <dl>
        <div><dt>平台</dt><dd>{item.platform ? <PlatformIdentity platform={item.platform} size="sm" /> : '未记录'}</dd></div>
        <div><dt>内容形式</dt><dd>{contentTypeLabel(item.contentType)}</dd></div>
        <div><dt>有效期</dt><dd>{validityLabel(item.validFrom, item.validUntil)}</dd></div>
        <div><dt>授权范围</dt><dd>{authorizationLabel(item.authorizationScope)}</dd></div>
      </dl>
      <footer><code>{item.publicOpportunityId}</code><Link to="/campaigns">进入履约<ArrowRight size={14} /></Link></footer>
    </article>
  )
}

function ModelCard({ icon, title, detail, tags }: { icon: ReactNode; title: string; detail: string; tags: string[] }) {
  return <article className={styles.modelCard}><span>{icon}</span><div><strong>{title}</strong><p>{detail}</p><footer>{tags.map((tag) => <small key={tag}>{tag}</small>)}</footer></div></article>
}

function StatusBadge({ status }: { status: string }) {
  return <span className="mg-badge" data-tone={businessStatusTone(status)}>{statusLabel(status)}</span>
}

function OpportunityCollection({
  state,
  onRetry,
  onRegister,
}: {
  state: LoadState<OpportunityResponse>
  onRetry: () => void
  onRegister: () => void
}) {
  if (state.status === 'ready') {
    return state.data.items.length ? (
      <div className={styles.opportunityGrid}>{state.data.items.map((item) => <OpportunityCard key={item.publicOpportunityId} item={item} />)}</div>
    ) : (
      <SurfaceState
        kind="empty"
        title="还没有已授权商务机会"
        detail="先登记账号身份、当前报价和品牌项目，再进入商单生产与履约。"
        action={<button className="mg-btn mg-btn-primary" type="button" onClick={onRegister}>登记机会</button>}
      />
    )
  }

  if (state.status === 'loading') {
    return <SurfaceState kind="loading" title="正在读取商务机会" detail="正在读取当前账户可见的商务机会。" />
  }
  if (state.status === 'permission') {
    return <SurfaceState kind="permission" title="暂无查看权限" detail={state.error} />
  }
  if (state.status === 'notFound') {
    return <SurfaceState kind="notFound" title="记录不存在" detail={state.error} action={<button className="mg-btn mg-btn-primary" type="button" onClick={onRetry}>重新读取</button>} />
  }
  if (state.status === 'error') {
    return <SurfaceState kind="error" title="商务机会读取失败" detail={state.error} action={<button className="mg-btn mg-btn-primary" type="button" onClick={onRetry}>重新读取</button>} />
  }
  if (state.status === 'empty') {
    return <SurfaceState kind="empty" title="还没有已授权商务机会" detail="先登记账号身份、当前报价和品牌项目，再进入商单生产与履约。" action={<button className="mg-btn mg-btn-primary" type="button" onClick={onRegister}>登记机会</button>} />
  }
  return null
}

// Business-opportunity lifecycle state machine, independent from statusPresentation.ts's
// runStatusLabels (creation-run lifecycle) -- see dedup audit LE-07.
function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    active: '进行中', approved: '已批准', confirmed: '已确认', open: '开放', in_progress: '推进中',
    pending: '待处理', draft: '草稿', needs_review: '待复核', awaiting_confirmation: '待确认',
    completed: '已完成', closed: '已关闭', rejected: '已拒绝', expired: '已过期',
  }
  return labels[status] ?? '状态待确认'
}

function contentTypeLabel(value: string): string {
  const normalized = value.toLowerCase()
  if (normalized.includes('video') || value.includes('视频')) return '视频'
  if (normalized.includes('image') || value.includes('图文')) return '图文'
  return value || '未记录'
}

function validityLabel(from: string | null, until: string | null): string {
  if (!from && !until) return '未提供有效期'
  return `${from ? formatDate(from) : '不限起始'} — ${until ? formatDate(until) : '不限结束'}`
}

// Previously echoed the raw enum value (or '待确认') for an unrecognized authorizationScope,
// leaking an internal value into the UI -- switched to the shared fixed-fallback behavior, which
// is what this project's readable-fields rule requires everywhere else (cluster LE-14).
function authorizationLabel(value: string): string {
  return authorizationScopeDisplayLabel(value)
}

function readError(error: unknown): string {
  return describeBusinessError(error, {
    fallback: '商务机会暂时无法读取。',
    forbidden: '当前账户没有读取商务机会的权限。',
    notFound: '当前账户还没有商务机会记录。',
  })
}

function toOpportunityState(error: unknown): LoadState<OpportunityResponse> {
  const message = readError(error)
  return toResourceState(error, '商务机会', { forbidden: message, notFound: message, error: message })
}
