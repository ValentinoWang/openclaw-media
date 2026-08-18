export function isCurrentW1Request(
  requestGeneration: number,
  currentGeneration: number,
  signal: AbortSignal,
): boolean {
  return requestGeneration === currentGeneration && !signal.aborted
}
