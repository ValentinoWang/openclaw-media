import { useEffect, useRef, useState } from 'react'
import { secureUuid } from '../secureUuid'

export type ActionState = { kind: 'idle' | 'busy' | 'success' | 'error'; message: string }
export type LoadState<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: T }

export function useLoad<T>(loader: () => Promise<T>, dependencies: readonly unknown[]): LoadState<T> {
  const [state, setState] = useState<LoadState<T>>({ status: 'loading' })
  useEffect(() => { let active = true; setState({ status: 'loading' }); loader().then((data) => { if (active) setState({ status: 'ready', data }) }).catch((error: unknown) => { if (active) setState({ status: 'error', message: error instanceof Error ? error.message : '读取失败' }) }); return () => { active = false } }, dependencies)
  return state
}

export function useAdminAction(onComplete: () => void) {
  const [state, setState] = useState<ActionState>({ kind: 'idle', message: '' })
  const pending = useRef({ fingerprint: '', key: '' })
  async function run<T>(fingerprint: string, action: (key: string) => Promise<T>): Promise<T | null> {
    if (pending.current.fingerprint !== fingerprint) pending.current = { fingerprint, key: newIdempotencyKey('admin') }
    setState({ kind: 'busy', message: '正在提交' })
    try {
      const result = await action(pending.current.key)
      pending.current = { fingerprint: '', key: '' }
      setState({ kind: 'success', message: '操作已完成' })
      onComplete()
      return result
    } catch (error) {
      setState({ kind: 'error', message: error instanceof Error ? error.message : '操作未完成' })
      return null
    }
  }
  return { state, busy: state.kind === 'busy', run }
}

export function newIdempotencyKey(scope: string) { return `${scope}-${secureUuid()}` }
export function mutationFingerprint(path: string, method: string, payload: Record<string, unknown>) { return JSON.stringify([method, path, payload]) }
export function positiveId(value: string) { return /^[1-9][0-9]*$/.test(value) }
export const canonicalUuid = (value: string) => /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)
export function nonNegativeInteger(value: string) { return /^(0|[1-9][0-9]*)$/.test(value) }
export function positiveMoney(value: string) { return /^(?:0\.(?:0{0,7}[1-9][0-9]{0,7})|[1-9][0-9]{0,5}(?:\.[0-9]{1,8})?)$/.test(value) && Number(value) <= 100000 }
export function liandongPurchaseUrl(value?: string) { try { const url = new URL(value || ''); const host = url.hostname.toLowerCase().replace(/\.$/, ''); return url.protocol === 'https:' && !url.port && !url.username && !url.password && !url.hash && (host === 'ldxp.cn' || host.endsWith('.ldxp.cn')) } catch { return false } }

