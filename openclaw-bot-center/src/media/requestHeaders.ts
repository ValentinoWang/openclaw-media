// Shared header-assembly rules for mutation requests, used by both media
// HTTP transports (mediaProductHttpTransport.ts and mediaWebApi.ts).
//
// Baseline is mediaProductHttpTransport.ts's own request() method:
// - the Idempotency-Key header is added only when a key is present
// - the CSRF header is added only for session-authenticated mutations
// - a missing CSRF token on such a mutation throws locally instead of
//   sending an empty X-OpenClaw-CSRF header. Sending an empty header lets
//   the request reach the server, which rejects it with a generic
//   csrf_rejected 403 - the caller never learns the real, locally-known
//   cause (missing_csrf_token) and can't show a precise message or recover
//   without a full page reload.

export class MissingCsrfTokenError extends Error {
  constructor(context: string) {
    super(`${context} 需要 CSRF token。`)
    this.name = 'MissingCsrfTokenError'
  }
}

export type MutationHeadersOptions = {
  /** Session CSRF token, if one is currently known. */
  csrfToken?: string
  /** Idempotency-Key header value, if this request should carry one. */
  idempotencyKey?: string
  /** Whether this request is a mutation (non-GET/HEAD/OPTIONS). */
  isMutation: boolean
  /** The envelope's declared auth source; CSRF only applies to 'session'. */
  authSource?: string
  /** Label used in the thrown error's message, e.g. an operation id. */
  context?: string
}

/**
 * Builds the Idempotency-Key and X-OpenClaw-CSRF headers for a mutation
 * request. Throws MissingCsrfTokenError instead of emitting an empty CSRF
 * header when one is required but not available.
 */
export function mutationHeaders(options: MutationHeadersOptions): Record<string, string> {
  const headers: Record<string, string> = {}
  if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey
  if (options.authSource === 'session' && options.isMutation) {
    if (!options.csrfToken) throw new MissingCsrfTokenError(options.context ?? 'request')
    headers['X-OpenClaw-CSRF'] = options.csrfToken
  }
  return headers
}
