export type ConfirmationReceiptState =
  | "missing"
  | "invalid"
  | "expired"
  | "active";

export type ConfirmationReceiptProblem = Exclude<
  ConfirmationReceiptState,
  "active"
>;

type ReceiptWithExpiry = { expiresAt?: unknown } | null | undefined;

const RECEIPT_REQUIRED_CONFIRMATIONS = new Set([
  "universal_deletion",
  "creator_profile_upsert",
  "track_creator_membership_query",
]);

export function confirmationReceiptState(
  receipt: ReceiptWithExpiry,
  nowMs = Date.now(),
): ConfirmationReceiptState {
  if (receipt === null || receipt === undefined) return "missing";
  if (typeof receipt.expiresAt !== "string") return "invalid";
  const expiresAt = Date.parse(receipt.expiresAt);
  if (!Number.isFinite(expiresAt)) return "invalid";
  return expiresAt > nowMs ? "active" : "expired";
}

export function confirmationReceiptProblem(
  capabilityId: string,
  variantId: string,
  receipt: ReceiptWithExpiry,
  nowMs = Date.now(),
): ConfirmationReceiptProblem | null {
  if (
    variantId !== "confirm" ||
    !RECEIPT_REQUIRED_CONFIRMATIONS.has(capabilityId)
  ) {
    return null;
  }
  const state = confirmationReceiptState(receipt, nowMs);
  return state === "active" ? null : state;
}

export function confirmationReceiptProblemMessage(
  problem: ConfirmationReceiptProblem,
): string {
  if (problem === "missing") return "请先生成有效预览，再进入确认。";
  if (problem === "expired") return "预览已过期，请重新生成后再确认。";
  return "预览凭证无效，请重新生成后再确认。";
}
