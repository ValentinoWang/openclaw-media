import {
  apiBase,
  type OperationId,
  type ProductRequestEnvelope,
  type ProductTransport,
} from './generatedProductContract'

export class MediaProductHttpError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'MediaProductHttpError'
    this.status = status
    this.code = code
  }
}

export type MediaProductHttpTransportOptions = {
  getCsrfToken?: () => string | undefined
  getDeviceCredential?: () => string | undefined
  fetchImpl?: typeof fetch
}

function errorMessage(payload: unknown): { code: string; message: string } {
  if (!payload || typeof payload !== 'object') return { code: 'request_failed', message: '服务请求未完成。' }
  const value = payload as { error?: { code?: unknown; message?: unknown } }
  return {
    code: typeof value.error?.code === 'string' ? value.error.code : 'request_failed',
    message: typeof value.error?.message === 'string' ? value.error.message : '服务请求未完成。',
  }
}

export class MediaProductHttpTransport implements ProductTransport {
  private readonly getCsrfToken: () => string | undefined
  private readonly getDeviceCredential: () => string | undefined
  private readonly fetchImpl: typeof fetch

  constructor(options: MediaProductHttpTransportOptions = {}) {
    this.getCsrfToken = options.getCsrfToken ?? (() => undefined)
    this.getDeviceCredential = options.getDeviceCredential ?? (() => undefined)
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis)
  }

  async request<TResponse>(operationId: OperationId, envelope: ProductRequestEnvelope): Promise<TResponse> {
    if (envelope.idempotency === 'required' && !envelope.idempotencyKey) {
      throw new MediaProductHttpError(0, 'missing_idempotency_key', `${operationId} 需要幂等键。`)
    }
    const query = new URLSearchParams(envelope.query)
    const target = `${apiBase}${envelope.path}${query.size ? `?${query.toString()}` : ''}`
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (envelope.body !== undefined) headers['Content-Type'] = 'application/json'
    if (envelope.idempotencyKey) headers['Idempotency-Key'] = envelope.idempotencyKey
    const isMutation = envelope.method !== 'GET' && envelope.method !== 'HEAD' && envelope.method !== 'OPTIONS'
    if (envelope.authSource === 'session' && isMutation) {
      const csrfToken = this.getCsrfToken()
      if (!csrfToken) throw new MediaProductHttpError(0, 'missing_csrf_token', `${operationId} 需要 CSRF token。`)
      headers['X-OpenClaw-CSRF'] = csrfToken
    }
    if (envelope.authSource === 'device_credential' || envelope.authSource === 'session_or_device_credential') {
      const credential = this.getDeviceCredential()
      if (credential) headers.Authorization = `Bearer ${credential}`
      else if (envelope.authSource === 'device_credential') throw new MediaProductHttpError(0, 'missing_device_credential', '设备授权不可用。')
    }
    const response = await this.fetchImpl(target, {
      method: envelope.method,
      credentials: 'same-origin',
      headers,
      body: envelope.body === undefined ? undefined : JSON.stringify(envelope.body),
      signal: envelope.signal,
    })
    if (!response.ok) {
      const detail = errorMessage(await response.json().catch(() => null))
      throw new MediaProductHttpError(response.status, detail.code, detail.message)
    }
    if (response.status === 204) return undefined as TResponse
    try {
      return await response.json() as TResponse
    } catch {
      throw new MediaProductHttpError(response.status, 'invalid_response', '服务返回了无法识别的响应。')
    }
  }
}
