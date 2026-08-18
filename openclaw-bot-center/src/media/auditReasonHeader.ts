export const AUDIT_REASON_HEADER = "X-Audit-Reason" as const;
export const AUDIT_REASON_WIRE_PREFIX = "utf8-base64url-v1." as const;

const MAX_AUDIT_REASON_UTF8_BYTES = 1024;

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

/** Encodes the exact Unicode reason into an ASCII-only versioned wire value. */
export function encodeAuditReasonHeader(reason: string): string {
  if (reason.length === 0) throw new TypeError("audit reason must not be empty");
  const bytes = new TextEncoder().encode(reason);
  if (bytes.length > MAX_AUDIT_REASON_UTF8_BYTES) {
    throw new TypeError("audit reason exceeds 1024 UTF-8 bytes");
  }
  const payload = bytesToBase64(bytes)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/u, "");
  return AUDIT_REASON_WIRE_PREFIX + payload;
}

export function addAuditReasonHeader(
  headers: Record<string, string>,
  reason: string,
): void {
  headers[AUDIT_REASON_HEADER] = encodeAuditReasonHeader(reason);
}
