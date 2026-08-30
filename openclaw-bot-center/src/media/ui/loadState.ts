// Canonical ResourceState/LoadState discriminated union + AbortController-aware loading
// hook (cluster FE-04). 13 pages each defined their own version of this union and then
// hand-rolled the same `let active = true` + `new AbortController()` loading effect next
// to it (24 `let active` / 33 `new AbortController()` sites across 18 files per the audit).
//
// This is deliberately NOT frozen to PersonalWorkspaceShellPage's narrower 8-branch union
// (idle/loading/ready/empty/unauthorized/missingEntitlement/notFound/error) -- per the
// audit, the 13 prior unions' branch sets are genuinely different (AssetsPage has
// `waiting`, OverviewPage has `timeout`, DecisionsPage has `unavailable`, three admin
// pages have `idle`) and forcing every page onto one frozen union would make pages handle
// branches they never produce. What *was* real duplication -- and what this file
// consolidates -- is (a) the discriminant convention itself (`status`, not TracksPage's
// `kind` -- that one page's local union predates this file and is left alone; migrating it
// is a separate, purely mechanical rename tracked on its own) and (b) the loading-effect
// behavior: set loading, run the abortable loader, land on `ready` or hand the caught error
// to the caller's own classifier, treat AbortError as a return to `idle` rather than an
// error (only PersonalWorkspaceShellPage did this correctly before; every other hand-rolled
// copy would flash a spurious "read failed" state when a fast page change aborted an
// in-flight request -- see dedup audit FE-04 migration step 2b), and abort the in-flight
// request from the effect's cleanup.
//
// The error payload is `error: E` (default `string`), not `message`, so a caller that
// carries a structured error (RunsPage's PageReadError, AdminBillingPage's
// BillingRequestError) can plug it in as `E` without changing the discriminant shape.
//
// ordinaryPagePrimitives.tsx's own `LoadState<T>`/`useLoad`/`PageState` trio is left
// untouched -- it predates this file, has its own (narrower, `message`-keyed) shape with
// existing callers depending on it, and is out of this cluster's turf per the FE-01/FE-06
// precedent ("kept per audit hedge / other clusters' turf").
import { useEffect, useState } from "react";

export type LoadState<T, E = string> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "empty" }
  | { status: "permission"; error: E }
  | { status: "notFound"; error: E }
  | { status: "error"; error: E };

/** True for the fetch-abort exception a cancelled `AbortController` request raises. */
export function isAbortError(error: unknown): boolean {
  return (
    (typeof DOMException !== "undefined" && error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}

/**
 * Canonical abortable loading effect. `loader` receives the effect's AbortSignal so a
 * page change that aborts an in-flight request lands back on `idle` (via `isAbortError`)
 * instead of flashing an "error" surface state. `toErrorState` classifies any other caught
 * error into a `permission`/`notFound`/`error` branch -- pass a page's FE-05
 * `toResourceState`-derived function, or inline the classification for a one-off caller.
 */
export function useResource<T, E = string>(
  loader: (signal: AbortSignal) => Promise<T>,
  toErrorState: (error: unknown) => LoadState<T, E>,
  deps: readonly unknown[],
): LoadState<T, E> {
  const [state, setState] = useState<LoadState<T, E>>({ status: "loading" });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setState({ status: "loading" });
    loader(controller.signal)
      .then((data) => {
        if (active) setState({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (isAbortError(error)) {
          setState({ status: "idle" });
          return;
        }
        setState(toErrorState(error));
      });
    return () => {
      active = false;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}
