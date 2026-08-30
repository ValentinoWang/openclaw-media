// Shared search input (cluster FE-13). Structural + accessibility baseline is TracksPage's
// local `SearchBox` -- the only one of 7 near-identical search fields that wrapped its
// `<input>` in a `<label>` with a screen-reader-only caption span, `type="search"` and a
// `maxLength` cap, so promoting it fixes the missing accessible name and `type="search"` on
// the other 6 call sites as a byproduct.
//
// Styling lives in mediaPrimitives.css's `.mg-search` (global stylesheet, loaded once via
// main.tsx) rather than a page's CSS Module, same rationale as `SurfaceState`. `className`
// composes onto the wrapping `<label>` for a caller's own layout needs -- AdminAccessPage and
// RunsPage no longer get their absolute-positioned-icon treatment (this component's flex-row
// structure replaces it outright), while AssetsPage keeps stacking its own `.filterField`
// alongside `.mg-search` via this prop. A caller that needs a `<form onSubmit>` around the
// field (DecisionsPage/RunsPage/AdminAccessPage/AdminTenantsPage/AssetsPage) keeps that
// wrapper itself -- this component only renders the field, not a submit model.
import { Search } from "lucide-react";

export function SearchBox({
  value,
  onChange,
  label,
  disabled = false,
  maxLength = 160,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  /** Both the screen-reader-only caption and the input's placeholder. */
  label: string;
  disabled?: boolean;
  maxLength?: number;
  className?: string;
}) {
  return (
    <label className={className ? `mg-search ${className}` : "mg-search"}>
      <Search size={15} aria-hidden="true" />
      <span className="sr-only">{label}</span>
      <input
        type="search"
        value={value}
        placeholder={label}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        maxLength={maxLength}
      />
    </label>
  );
}
