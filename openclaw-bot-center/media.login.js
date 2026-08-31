import QRCode from 'qrcode'

const MEDIA_ROOT = '/openclaw/media'
const PERSONAL_ENDPOINTS = Object.freeze({
  login: '/openclaw/auth/login',
  register: '/openclaw/auth/register',
  verify: '/openclaw/auth/verify-email',
  resendVerification: '/openclaw/auth/verify-email/resend',
  recover: '/openclaw/auth/recover',
  reset: '/openclaw/auth/reset',
})
const SESSION_ENDPOINT = '/openclaw/media/api/session'
const FALLBACK_RETURN = `${MEDIA_ROOT}/overview`

function isAllowedMediaPath(pathname) {
  return pathname === MEDIA_ROOT || pathname.startsWith(`${MEDIA_ROOT}/`)
}

function safeUserNext(search = window.location.search) {
  const requested = new URLSearchParams(search).get('next')
  if (!requested) return FALLBACK_RETURN
  try {
    const target = new URL(requested, window.location.origin)
    const isSafe = target.origin === window.location.origin &&
      !target.username &&
      !target.password &&
      isAllowedMediaPath(target.pathname)
    if (!isSafe || target.pathname === `${MEDIA_ROOT}/login` || target.pathname.startsWith(`${MEDIA_ROOT}/admin`)) {
      return FALLBACK_RETURN
    }
    return `${target.pathname}${target.search}${target.hash}`
  } catch {
    return FALLBACK_RETURN
  }
}

function setHref(id, href) {
  const link = document.querySelector(`#${id}`)
  if (link) link.setAttribute('href', href)
}

function setText(id, message) {
  const element = document.querySelector(`#${id}`)
  if (element) element.textContent = message
}

function setHidden(id, hidden) {
  const element = document.querySelector(`#${id}`)
  if (element) element.hidden = hidden
}

function setBusy(button, busy, busyLabel, idleLabel) {
  if (!button) return
  button.disabled = busy
  button.textContent = busy ? busyLabel : idleLabel
}

const AUTH_REQUEST_TIMEOUT_MS = 5000

async function fetchWithTimeout(path, options = {}) {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), AUTH_REQUEST_TIMEOUT_MS)
  try {
    return await fetch(path, { ...options, signal: controller.signal })
  } finally {
    window.clearTimeout(timeout)
  }
}

async function postJson(path, body) {
  return fetchWithTimeout(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(body),
  })
}

function errorCode(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null
  const error = payload.error
  if (!error || typeof error !== 'object' || Array.isArray(error)) return null
  return typeof error.code === 'string' ? error.code : null
}

function errorMessage(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null
  const error = payload.error
  if (!error || typeof error !== 'object' || Array.isArray(error)) return null
  return typeof error.message === 'string' && error.message.trim() ? error.message.trim() : null
}

class AuthRequestError extends Error {
  constructor(code, status, message) {
    super(message)
    this.name = 'AuthRequestError'
    this.code = code
    this.status = status
  }
}

function organizationAuthResponseError(response, payload, fallbackCode = `http_${response.status}`) {
  return new AuthRequestError(
    errorCode(payload) || fallbackCode,
    response.status,
    errorMessage(payload) || '组织授权暂时不可用，请稍后重试。',
  )
}

function registrationError(payload) {
  const code = errorCode(payload)
  if (code === 'duplicate_username') return '这个用户名已被使用，请更换后重试。'
  if (code === 'invalid_request') return errorMessage(payload) || '请检查用户名、邮箱和密码格式。'
  if (code === 'rate_limited') return '操作过于频繁，请稍后再试。'
  if (code === 'admission_required') return '当前注册需要邀请或准入码，请联系管理员。'
  if (code === 'admission_unavailable' || code === 'affiliate_unavailable') return '邀请或准入码无效，请重新确认后再试。'
  if (code === 'account_exists') return '用户名或邮箱已被使用，请更换后重试。'
  if (code === 'email_delivery_unavailable') {
    return '邮箱验证邮件暂时无法发送，请稍后重试。'
  }
  if (code === 'account_database_unavailable' || code === 'internal_error') {
    return '注册服务暂时不可用，请稍后重试。'
  }
  return errorMessage(payload) || '注册服务返回了无效响应，请稍后重试。'
}

function passwordResetError(payload) {
  const code = errorCode(payload)
  if (code === 'invalid_request') return errorMessage(payload) || '请检查新密码格式。'
  if (code === 'rate_limited') return '操作过于频繁，请稍后再试。'
  return '找回链接已失效或已使用，请重新申请找回邮件。'
}

function parseMediaSessionEnvelope(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null
  if (Object.keys(payload).length !== 3 || payload.schemaVersion !== 'media_web_business_pages_v2' || !Number.isInteger(payload.revision) || payload.revision < 1) return null
  const session = payload.session
  if (!session || typeof session !== 'object' || Array.isArray(session) || Object.keys(session).length !== 11) return null
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
  if (typeof session.publicUserId !== 'string' || !uuid.test(session.publicUserId) ||
    typeof session.tenantId !== 'string' || !uuid.test(session.tenantId) ||
    (session.role !== 'ordinary' && session.role !== 'admin') ||
    (session.memberRole !== 'owner' && session.memberRole !== 'member') ||
    typeof session.maintainer !== 'boolean' || (session.maintainer && session.role !== 'admin') ||
    typeof session.csrfToken !== 'string' || typeof session.expiresAt !== 'string' ||
    Number.isNaN(Date.parse(session.expiresAt)) || session.schemaVersion !== 'media_web_business_pages_v2') return null
  const personal = session.workspaceMode === 'personal_web' &&
    session.editorMode === 'web_edit' && session.bodyAuthority === 'internal'
  const organization = session.workspaceMode === 'organization_lark' &&
    session.editorMode === 'lark_edit' && session.bodyAuthority === 'lark'
  if (!personal && !organization) return null
  return session
}

async function roleLanding() {
  const response = await fetchWithTimeout(SESSION_ENDPOINT, { credentials: 'same-origin' })
  const session = parseMediaSessionEnvelope(await response.json().catch(() => null))
  if (!response.ok || !session) throw new Error('session_not_ready')
  if (session.role === 'admin') return `${MEDIA_ROOT}/admin/overview`
  return safeUserNext()
}

function parseLoginStart(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload) || payload.ok !== true) return null
  let authorization
  try { authorization = new URL(payload.authorizationUrl) } catch { return null }
  if (authorization.protocol !== 'https:' || !['accounts.feishu.cn', 'open.feishu.cn'].includes(authorization.hostname)) return null
  if (typeof payload.expiresAt !== 'string' || Number.isNaN(Date.parse(payload.expiresAt))) return null
  if (!Number.isInteger(payload.maximumAge) || payload.maximumAge < 60 || payload.maximumAge > 300) return null
  return {
    authorizationUrl: authorization.href,
    expiresAt: payload.expiresAt,
  }
}

let organizationRun = 0
let entryStateRun = 0
let organizationAuthInFlight = null

const ENTRY_STATES = new Set(['matched', 'none', 'expired', 'mismatched'])

function setQueryMode(mode, { replace = false } = {}) {
  const url = new URL(window.location.href)
  if (mode === 'personal' || mode === 'organization') url.searchParams.set('mode', mode)
  else url.searchParams.delete('mode')
  const nextUrl = `${url.pathname}${url.search}${url.hash}`
  const currentUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`
  if (nextUrl === currentUrl) return false
  const method = replace ? 'replaceState' : 'pushState'
  window.history[method]({ mode: mode || null }, '', nextUrl)
  return true
}

async function fetchEntryState(mode, run) {
  try {
    const response = await fetchWithTimeout(`/openclaw/auth/entry-state?mode=${encodeURIComponent(mode)}`, {
      credentials: 'same-origin',
    })
    const payload = await response.json().catch(() => null)
    if (run !== entryStateRun) return null
    if (!response.ok || !payload || payload.schemaVersion !== 'media_auth_entry_state_v1' ||
      payload.mode !== mode || !ENTRY_STATES.has(payload.state)) return null
    return payload
  } catch {
    return null
  }
}

function renderEntryState(mode, state, payload = null) {
  const prefix = `${mode}-entry`
  const root = document.querySelector(`#${prefix}-state`)
  if (!root) return
  root.dataset.state = state
  root.setAttribute('aria-busy', String(state === 'loading'))
  const badge = document.querySelector(`#${prefix}-badge`)
  const labels = {
    loading: '正在检查',
    matched: '可直接进入',
    none: '需要授权',
    expired: '会话已过期',
    mismatched: '工作区不匹配',
    unavailable: '暂时无法确认',
  }
  if (badge) badge.textContent = labels[state] || labels.unavailable
  const visibleView = state === 'unavailable' || state === 'none' || state === 'expired' || state === 'mismatched' ? 'fallback' : state
  document.querySelectorAll(`#${prefix}-state [data-entry-view]`).forEach((view) => {
    view.hidden = view.dataset.entryView !== visibleView
  })
  if (state === 'matched' && payload?.entry) {
    setText(`${prefix}-label`, payload.entry.displayLabel || '')
    setText(`${prefix}-identity`, payload.entry.maskedIdentity || '')
    const expiry = document.querySelector(`#${prefix}-expires`)
    if (expiry) {
      expiry.textContent = payload.entry.expiresAt ? new Date(payload.entry.expiresAt).toLocaleString('zh-CN') : ''
      expiry.dateTime = payload.entry.expiresAt || ''
    }
  }
  if (state === 'none' || state === 'expired' || state === 'mismatched' || state === 'unavailable') {
    const message = mode === 'personal'
      ? state === 'expired' ? '当前个人会话已过期，请使用账号密码登录。' : '当前浏览器没有可用的个人会话，请使用账号密码登录。'
      : state === 'expired' ? '当前组织会话已过期，请重新使用 Feishu 授权。'
        : state === 'mismatched' ? '当前会话属于其他工作区，请选择对应的登录方式。'
          : '当前浏览器没有可用的组织会话，请使用 Feishu 授权。'
    setText(`${prefix}-fallback-message`, message)
  }
}

async function loadEntryState(mode) {
  const run = ++entryStateRun
  setHidden(`${mode}-entry-state`, false)
  renderEntryState(mode, 'loading')
  const payload = await fetchEntryState(mode, run)
  if (run !== entryStateRun) return
  const state = payload?.state || 'unavailable'
  renderEntryState(mode, state, payload)
  if (mode === 'personal') {
    setHidden('personal-password-fallback', state !== 'none' && state !== 'expired' && state !== 'mismatched' && state !== 'unavailable')
  } else {
    setHidden('organization-oauth-fallback', state === 'matched')
    if (state !== 'matched') void startOrganizationAuth()
  }
}

function setOrganizationAuthBusy(busy) {
  const refresh = document.querySelector('#qr-refresh')
  if (refresh) {
    refresh.disabled = busy
    refresh.setAttribute('aria-busy', String(busy))
  }
  const fallback = document.querySelector('#organization-entry-fallback')
  if (fallback) fallback.disabled = busy
}

async function startOrganizationAuth() {
  if (organizationAuthInFlight) return organizationAuthInFlight
  const run = ++organizationRun
  const task = (async () => {
    setOrganizationAuthBusy(true)
    setHidden('qr-refresh', true)
    setHidden('mobile-authorize', true)
    setHidden('qr-placeholder', false)
    setText('qr-placeholder', '正在生成授权二维码')
    setText('qr-status', '正在连接 Feishu 授权服务...')
    const qrStatus = document.querySelector('#qr-status')
    if (qrStatus) {
      delete qrStatus.dataset.errorCode
      delete qrStatus.dataset.errorStatus
    }
    const qrCanvas = document.querySelector('#qr-canvas')
    const context = qrCanvas?.getContext('2d')
    context?.clearRect(0, 0, qrCanvas.width, qrCanvas.height)
    try {
      const response = await postJson('/openclaw/media/auth/feishu/start', { workspaceIntent: 'organization_lark' })
      const payload = await response.json().catch(() => null)
      if (!response.ok) throw organizationAuthResponseError(response, payload)
      const started = parseLoginStart(payload)
      if (!started) throw organizationAuthResponseError(response, payload, 'invalid_response')
      if (run !== organizationRun) return
      await QRCode.toCanvas(qrCanvas, started.authorizationUrl, {
        width: 200,
        margin: 1,
        errorCorrectionLevel: 'M',
        color: { dark: '#20242c', light: '#ffffff' },
      })
      qrCanvas.style.removeProperty('width')
      qrCanvas.style.removeProperty('height')
      if (run !== organizationRun) return
      setHidden('qr-placeholder', true)
      const mobileAuthorize = document.querySelector('#mobile-authorize')
      if (mobileAuthorize) mobileAuthorize.href = started.authorizationUrl
      setHidden('mobile-authorize', false)
      setText('qr-status', '请使用 Feishu 扫码，或点击按钮在当前设备完成授权。')
    } catch (caught) {
      if (run !== organizationRun) return
      setText('qr-placeholder', '授权二维码暂不可用')
      const timedOut = caught instanceof Error && (caught.name === 'AbortError' || caught.message === 'auth_request_timeout')
      if (qrStatus && caught instanceof AuthRequestError) {
        qrStatus.dataset.errorCode = caught.code
        qrStatus.dataset.errorStatus = String(caught.status)
      }
      setText('qr-status', timedOut ? '组织授权服务暂时不可用，请稍后重试。' : caught instanceof Error ? caught.message : '组织授权暂时不可用。')
      setHidden('qr-refresh', false)
    } finally {
      if (run === organizationRun) setOrganizationAuthBusy(false)
    }
  })()
  organizationAuthInFlight = task
  void task.then(
    () => { if (organizationAuthInFlight === task) organizationAuthInFlight = null },
    () => { if (organizationAuthInFlight === task) organizationAuthInFlight = null },
  )
  return task
}

function credentialError(payload) {
  const code = errorCode(payload)
  if (code === 'email_verification_required' || code === 'pending_email_verification') {
    return { message: '账号或密码错误。完成凭据确认后，请完成邮箱验证。', pending: true }
  }
  if (code === 'suspended' || code === 'invalid_credentials' || code === 'account_not_found') {
    return { message: '账号或密码错误。', pending: false }
  }
  return { message: '账号或密码错误。', pending: false }
}

function setLoginLinks() {
  const next = safeUserNext()
  const query = `?next=${encodeURIComponent(next)}`
  setHref('register-link', `${MEDIA_ROOT}/register${query}`)
  setHref('recover-link', `${MEDIA_ROOT}/recover${query}`)
  setHref('pending-verify-link', `${MEDIA_ROOT}/verify${query}`)
}

function initPersonalLogin() {
  const form = document.querySelector('#login-form')
  const identifier = document.querySelector('#identifier')
  const password = document.querySelector('#password')
  const submit = document.querySelector('#submit')
  if (!form || !identifier || !password || !submit) return
  setLoginLinks()
  form.addEventListener('submit', async (event) => {
    event.preventDefault()
    const error = document.querySelector('#error')
    const pendingGuidance = document.querySelector('#pending-guidance')
    if (!form.reportValidity()) return
    if (error) error.textContent = ''
    if (pendingGuidance) pendingGuidance.hidden = true
    setBusy(submit, true, '正在登录...', '登录')
    try {
      const response = await postJson(PERSONAL_ENDPOINTS.login, {
        identifier: identifier.value.trim(),
        password: password.value,
      })
      const payload = await response.json().catch(() => null)
      if (!response.ok || payload?.ok !== true) {
        const safeError = credentialError(payload)
        if (error) error.textContent = safeError.message
        if (pendingGuidance) pendingGuidance.hidden = !safeError.pending
        return
      }
      window.location.replace(await roleLanding())
    } catch {
      if (error) error.textContent = '登录服务暂时不可用，请稍后重试。'
    } finally {
      setBusy(submit, false, '正在登录...', '登录')
    }
  })
}

function initLogin() {
  const personalChoice = document.querySelector('#personal-choice')
  const organizationChoice = document.querySelector('#organization-choice')
  const personalPanel = document.querySelector('#password-panel')
  const organizationPanel = document.querySelector('#organization-panel')
  if (!personalChoice || !organizationChoice || !personalPanel || !organizationPanel) return
  initPersonalLogin()

  const choices = [personalChoice, organizationChoice]
  let activeMode = null
  const selectMode = (mode, moveFocus = true, historyMode = 'push') => {
    if (mode !== 'personal' && mode !== 'organization') return
    if (historyMode) setQueryMode(mode, { replace: historyMode === 'replace' })
    if (activeMode === mode) return
    activeMode = mode
    const personal = mode === 'personal'
    personalChoice.setAttribute('aria-selected', String(personal))
    organizationChoice.setAttribute('aria-selected', String(!personal))
    personalPanel.hidden = !personal
    organizationPanel.hidden = personal
    if (personal) {
      ++organizationRun
      organizationAuthInFlight = null
      setHidden('personal-password-fallback', true)
      setText('choice-status', '已选择个人创作者，请使用平台账号登录。')
      if (moveFocus) document.querySelector('#identifier')?.focus()
    } else {
      setText('choice-status', '已选择组织成员，继续使用 Feishu 完成授权。')
      if (moveFocus) document.querySelector('#organization-back')?.focus()
    }
    void loadEntryState(mode)
  }

  const resetMode = (historyMode = 'push') => {
    if (historyMode) setQueryMode(null, { replace: historyMode === 'replace' })
    if (activeMode === null) return
    activeMode = null
    ++organizationRun
    organizationAuthInFlight = null
    ++entryStateRun
    personalPanel.hidden = true
    organizationPanel.hidden = true
    personalChoice.setAttribute('aria-selected', 'false')
    organizationChoice.setAttribute('aria-selected', 'false')
    setText('choice-status', '请选择一个身份继续。')
  }

  choices.forEach((choice, index) => {
    choice.addEventListener('click', () => selectMode(choice.dataset.mode, true, 'push'))
    choice.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
      event.preventDefault()
      const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? choices.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + choices.length) % choices.length
      choices[nextIndex].focus()
      selectMode(choices[nextIndex].dataset.mode, false, 'push')
    })
  })
  document.querySelector('#personal-back')?.addEventListener('click', () => {
    resetMode('push')
    personalChoice.focus()
  })
  document.querySelector('#organization-back')?.addEventListener('click', () => {
    resetMode('push')
    organizationChoice.focus()
  })
  document.querySelector('#qr-refresh')?.addEventListener('click', () => void startOrganizationAuth())
  document.querySelector('#personal-entry-fallback')?.addEventListener('click', () => {
    ++entryStateRun
    setHidden('personal-entry-state', true)
    setHidden('personal-password-fallback', false)
    document.querySelector('#identifier')?.focus()
  })
  document.querySelector('#organization-entry-fallback')?.addEventListener('click', () => {
    ++entryStateRun
    setHidden('organization-entry-state', true)
    setHidden('organization-oauth-fallback', false)
    void startOrganizationAuth()
  })
  document.querySelector('#personal-entry-continue')?.addEventListener('click', async () => {
    setBusy(document.querySelector('#personal-entry-continue'), true, '正在进入...', '继续进入')
    try { window.location.replace(await roleLanding()) } catch { renderEntryState('personal', 'unavailable') }
    finally { setBusy(document.querySelector('#personal-entry-continue'), false, '正在进入...', '继续进入') }
  })
  document.querySelector('#organization-entry-continue')?.addEventListener('click', async () => {
    setBusy(document.querySelector('#organization-entry-continue'), true, '正在进入...', '继续进入')
    try { window.location.replace(await roleLanding()) } catch { renderEntryState('organization', 'unavailable') }
    finally { setBusy(document.querySelector('#organization-entry-continue'), false, '正在进入...', '继续进入') }
  })
  window.addEventListener('popstate', () => {
    const mode = new URLSearchParams(window.location.search).get('mode')
    if (mode === 'personal' || mode === 'organization') selectMode(mode, false, null)
    else resetMode(null)
  })
  const initialMode = new URLSearchParams(window.location.search).get('mode')
  if (initialMode === 'personal' || initialMode === 'organization') selectMode(initialMode, false, 'replace')
  else {
    if (initialMode) setQueryMode(null, { replace: true })
    resetMode(null)
  }
}

function initRegister() {
  const form = document.querySelector('#register-form')
  const submit = document.querySelector('#register-submit')
  const resend = document.querySelector('#register-resend')
  if (!form || !submit) return
  let submittedIdentifier = ''
  const next = `?next=${encodeURIComponent(safeUserNext())}`
  setHref('register-login-link', `${MEDIA_ROOT}/login${next}`)
  setHref('register-login-secondary', `${MEDIA_ROOT}/login${next}`)
  form.addEventListener('submit', async (event) => {
    event.preventDefault()
    if (!form.reportValidity()) return
    setText('register-error', '')
    setBusy(submit, true, '正在创建...', '创建账号')
    try {
      const response = await postJson(PERSONAL_ENDPOINTS.register, {
        username: document.querySelector('#username').value.trim(),
        email: document.querySelector('#email').value.trim(),
        password: document.querySelector('#password').value,
      })
      const payload = await response.json().catch(() => null)
      if (!response.ok || payload?.ok !== true) {
        setText('register-error', registrationError(payload))
        return
      }
      submittedIdentifier = document.querySelector('#email').value.trim()
      form.hidden = true
      setHidden('register-success', false)
    } catch {
      setText('register-error', '注册服务暂时不可用，请稍后重试。')
    } finally {
      setBusy(submit, false, '正在创建...', '创建账号')
    }
  })
  resend?.addEventListener('click', async () => {
    if (!submittedIdentifier) return
    setText('register-resend-message', '')
    setBusy(resend, true, '正在发送...', '重发验证邮件')
    try {
      const response = await postJson(PERSONAL_ENDPOINTS.resendVerification, {
        identifier: submittedIdentifier,
      })
      const payload = await response.json().catch(() => null)
      if (!response.ok) {
        setText('register-resend-message', registrationError(payload))
        return
      }
      setText('register-resend-message', '如果账号符合条件，我们会发送验证邮件，请使用最新邮件完成验证。')
    } catch {
      setText('register-resend-message', '验证邮件服务暂时不可用，请稍后重试。')
    } finally {
      setBusy(resend, false, '正在发送...', '重发验证邮件')
    }
  })
}

function initVerify() {
  const form = document.querySelector('#verify-form')
  const resend = document.querySelector('#resend-submit')
  const verifySubmit = document.querySelector('#verify-submit')
  if (!form || !resend || !verifySubmit) return
  const next = `?next=${encodeURIComponent(safeUserNext())}`
  setHref('verify-login-link', `${MEDIA_ROOT}/login${next}`)
  setHref('verify-login-secondary', `${MEDIA_ROOT}/login${next}`)
  const query = new URLSearchParams(window.location.search)
  const verificationToken = query.get('token')?.trim() || ''
  if (verificationToken) {
    setHidden('verify-action', false)
    setText('verify-link-hint', '验证链接已就绪。确认后账号会启用，但页面不会自动登录。')
  }
  verifySubmit.addEventListener('click', async () => {
    if (!verificationToken) {
      setText('verify-message', '请从验证邮件打开此页，或重发最新验证邮件。')
      return
    }
    setBusy(verifySubmit, true, '正在确认...', '确认验证邮箱')
    try {
      const response = await postJson(PERSONAL_ENDPOINTS.verify, { token: verificationToken })
      const payload = await response.json().catch(() => null)
      if (!response.ok || payload?.ok !== true) {
        setText('verify-message', '验证链接已失效或已使用，请重发最新验证邮件。')
        return
      }
      setHidden('verify-action', true)
      form.hidden = true
      setHidden('verify-success', false)
      setText('verify-message', '')
    } catch {
      setText('verify-message', '验证服务暂时不可用，请稍后重试。')
    } finally {
      setBusy(verifySubmit, false, '正在确认...', '确认验证邮箱')
    }
  })
  form.addEventListener('submit', async (event) => {
    event.preventDefault()
    if (!form.reportValidity()) return
    setText('verify-message', '')
    setBusy(resend, true, '正在发送...', '重发验证邮件')
    try {
      const response = await postJson(PERSONAL_ENDPOINTS.resendVerification, {
        identifier: document.querySelector('#verify-identifier').value.trim(),
      })
      const payload = await response.json().catch(() => null)
      if (!response.ok) {
        setText('verify-message', registrationError(payload))
        return
      }
      setText('verify-message', '如果账号符合条件，我们会发送验证邮件，请使用最新邮件完成验证。')
    } catch {
      setText('verify-message', '验证邮件服务暂时不可用，请稍后重试。')
    } finally {
      setBusy(resend, false, '正在发送...', '重发验证邮件')
    }
  })
}

function initRecover() {
  const form = document.querySelector('#recover-form')
  const submit = document.querySelector('#recover-submit')
  if (!form || !submit) return
  const next = `?next=${encodeURIComponent(safeUserNext())}`
  setHref('recover-login-link', `${MEDIA_ROOT}/login${next}`)
  setHref('recover-login-secondary', `${MEDIA_ROOT}/login${next}`)
  form.addEventListener('submit', async (event) => {
    event.preventDefault()
    if (!form.reportValidity()) return
    setText('recover-message', '')
    setBusy(submit, true, '正在处理...', '发送找回邮件')
    try {
      const response = await postJson(PERSONAL_ENDPOINTS.recover, {
        identifier: document.querySelector('#recover-identifier').value.trim(),
      })
      await response.json().catch(() => null)
      if (!response.ok) {
        setText('recover-message', '如果账号符合条件，我们会发送邮件。')
        return
      }
      form.hidden = true
      setHidden('recover-success', false)
    } catch {
      setText('recover-message', '找回服务暂时不可用，请稍后重试。')
    } finally {
      setBusy(submit, false, '正在处理...', '发送找回邮件')
    }
  })
}

function initReset() {
  const form = document.querySelector('#reset-form')
  const submit = document.querySelector('#reset-submit')
  if (!form || !submit) return
  const next = `?next=${encodeURIComponent(safeUserNext())}`
  setHref('reset-login-link', `${MEDIA_ROOT}/login${next}`)
  setHref('reset-recover-link', `${MEDIA_ROOT}/recover${next}`)
  const resetToken = new URLSearchParams(window.location.search).get('token')?.trim() || ''
  form.addEventListener('submit', async (event) => {
    event.preventDefault()
    if (!resetToken) {
      setText('reset-message', '请从找回邮件打开此页。')
      return
    }
    if (!form.reportValidity()) return
    const password = document.querySelector('#reset-password').value
    const confirmation = document.querySelector('#reset-confirm-password').value
    if (password !== confirmation) {
      setText('reset-message', '两次输入的密码不一致。')
      return
    }
    setText('reset-message', '')
    setBusy(submit, true, '正在保存...', '保存新密码')
    try {
      const response = await postJson(PERSONAL_ENDPOINTS.reset, { token: resetToken, newPassword: password })
      const payload = await response.json().catch(() => null)
      if (!response.ok || payload?.ok !== true) {
        setText('reset-message', passwordResetError(payload))
        return
      }
      form.hidden = true
      setHidden('reset-success', false)
    } catch {
      setText('reset-message', '重置服务暂时不可用，请稍后重试。')
    } finally {
      setBusy(submit, false, '正在保存...', '保存新密码')
    }
  })
}

if (typeof document !== 'undefined') {
  const page = document.body?.dataset.authPage
  if (page === 'login') initLogin()
  if (page === 'register') initRegister()
  if (page === 'verify') initVerify()
  if (page === 'recover') initRecover()
  if (page === 'reset') initReset()
}

export { parseLoginStart, parseMediaSessionEnvelope, roleLanding, safeUserNext }
