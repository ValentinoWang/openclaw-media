import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { resolveStudioRoutePolicy, studioShellNavigationModes } from '../../src/media/mediaStudioRoutePolicy'

// Guard card: compact-shell responsive boundary and combobox accessibility.
// Failure class: a responsive CSS edit or a simplified search result can silently
// remove the approved rail/drawer split or keyboard route selection. Repair the
// source boundary and ARIA state model, then keep the synthetic rejection below.
const projectRoot = resolve(import.meta.dirname, '../..')
const appSource = readFileSync(resolve(projectRoot, 'src/media/MediaStudioApp.tsx'), 'utf8')
const themeSource = readFileSync(resolve(projectRoot, 'src/media/mediaStudioTheme.css'), 'utf8')
const workspaceSource = readFileSync(resolve(projectRoot, 'src/media/WorkspaceShellPage.tsx'), 'utf8')

function requireContract(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`Media Studio shell contract failed: ${message}`)
}

function extractBlock(source: string, marker: string): string {
  const markerStart = source.indexOf(marker)
  requireContract(markerStart >= 0, `missing block marker ${marker}`)
  const blockStart = source.indexOf('{', markerStart + marker.length)
  requireContract(blockStart >= 0, `missing opening brace for ${marker}`)

  let depth = 0
  for (let index = blockStart; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1
    if (source[index] === '}') depth -= 1
    if (depth === 0) return source.slice(markerStart, index + 1)
  }
  throw new Error(`Media Studio shell contract failed: unterminated block ${marker}`)
}

function requireRejected(mutatedSource: string, check: (source: string) => boolean, fixture: string, repair: string): void {
  assert.equal(check(mutatedSource), false, `Media Studio shell contract negative proof failed: ${fixture}. Repair: ${repair}`)
}

requireContract(
  appSource.includes('const flatNavigation = useMemo(() => navigation.flatMap((group) => group.items), [navigation])'),
  'visible navigation must flatten the resolved route-policy navigation',
)
requireContract(appSource.includes('const visibleNavigationItemCount = flatNavigation.length'), 'visible navigation item count is missing')
requireContract(appSource.includes("const isCompactNavigation = visibleNavigationItemCount < 3 && routePolicy.navigationMode === 'compact'"), 'compact navigation is not count-derived and shell-policy guarded')
requireContract(appSource.includes("isCompactNavigation ? 'is-compact-navigation' : ''"), 'compact navigation shell marker is missing')

assert.deepEqual(
  studioShellNavigationModes,
  { admin: 'full', personal: 'full', organization: 'compact' },
  'shell navigation outcomes drifted from the approved full/compact boundary',
)
const shellFixtures = [
  [{ role: 'admin', workspaceMode: 'personal_web', bodyAuthority: 'internal' }, 'admin', 'full'],
  [{ role: 'ordinary', workspaceMode: 'personal_web', bodyAuthority: 'internal' }, 'personal', 'full'],
  [{ role: 'ordinary', workspaceMode: 'organization_lark', bodyAuthority: 'lark' }, 'organization', 'compact'],
] as const
for (const [session, expectedShell, expectedMode] of shellFixtures) {
  const policy = resolveStudioRoutePolicy(session)
  assert.equal(policy.shell, expectedShell)
  assert.equal(policy.navigationMode, expectedMode)
  assert.equal(policy.navigationMode === 'compact', policy.shell === 'organization', 'compact mode escaped its allowed shell')
}
requireContract(workspaceSource.includes('data-page-ownership="router" data-accent={accent}'), 'workspace fallback ownership/accent markers drifted')
requireContract(workspaceSource.includes('action: null'), 'workspace fallback action contract is not explicitly null')
requireContract((workspaceSource.match(/<WorkspaceFallback/g) ?? []).length === 3, 'workspace fallback call count drifted')
requireContract((workspaceSource.match(/action=\{null\}/g) ?? []).length === 3, 'workspace fallback calls must explicitly suppress SurfaceState actions')

const desktopCompactBlock = extractBlock(themeSource, '@media (min-width: 1121px)')
requireContract(desktopCompactBlock.includes('.studio-shell.is-compact-navigation .studio-sidebar'), 'compact rail selector is missing')
requireContract(desktopCompactBlock.includes('width: 56px'), 'compact rail width must be exactly 56px')
requireContract(desktopCompactBlock.includes('.studio-shell.is-compact-navigation .studio-workspace'), 'compact workspace selector is missing')
requireContract(desktopCompactBlock.includes('margin-left: 56px'), 'compact workspace offset must be exactly 56px')
requireContract(desktopCompactBlock.includes('.studio-shell.is-compact-navigation .studio-nav-link'), 'compact destinations are not styled as rail links')
requireContract(desktopCompactBlock.includes('grid-template-columns: 25px'), 'compact destinations must reserve a stable icon column')
requireContract(desktopCompactBlock.includes('.studio-shell.is-compact-navigation .studio-nav-link.active'), 'compact active state is missing')
requireContract(desktopCompactBlock.includes('.studio-shell.is-compact-navigation .studio-account-button'), 'compact account control is missing')
requireContract(desktopCompactBlock.includes('.studio-shell.is-compact-navigation .studio-account-popover'), 'compact account popover placement is missing')
requireContract(desktopCompactBlock.includes('.studio-shell.is-compact-navigation .studio-brand'), 'compact brand placement is missing')
requireRejected(
  desktopCompactBlock.replace('width: 56px', 'width: 57px'),
  (source) => source.includes('width: 56px'),
  'the compact rail width changed from 56px',
  'restore width: 56px inside @media (min-width: 1121px)',
)

requireContract(appSource.includes('<NavLink className="studio-brand" to={defaultRoute}'), 'brand is not keyboard-usable as a route link')
requireContract(appSource.includes('aria-label="MediaClaw 工作台" title="MediaClaw 工作台"'), 'brand lacks an accessible name and pointer tooltip')
requireContract(appSource.includes('id="studio-mobile-navigation"'), 'mobile drawer lacks a stable accessible target id')
requireContract(appSource.includes("aria-label={menuOpen ? '关闭导航' : '打开导航'}"), 'mobile menu label is not state-aware')
requireContract(appSource.includes('aria-expanded={menuOpen} aria-controls="studio-mobile-navigation"'), 'mobile menu button lacks expanded/controls semantics')
requireContract(appSource.includes('to={item.path}'), 'navigation destinations are missing their route targets')
requireContract(appSource.includes('aria-label={item.detail ? `${item.label}：${item.detail}` : item.label}'), 'compact destinations lack explicit screen-reader names')
requireContract(appSource.includes('title={item.label}'), 'compact destinations lack explicit pointer tooltips')
requireContract(appSource.includes('<span className="studio-nav-copy"><strong>{item.label}</strong>'), 'navigation labels were removed from the DOM')
requireContract(!appSource.includes('tabIndex={-1}'), 'compact destinations must remain keyboard reachable')
requireContract(appSource.includes('aria-haspopup="menu"'), 'account control must expose its menu relationship')
requireContract(appSource.includes('aria-controls="studio-account-popover"'), 'account control must reference its popover')
requireContract(appSource.includes('id="studio-account-popover" className="studio-account-popover" role="menu"'), 'account popover semantics are incomplete')
requireContract(appSource.includes('role="menuitem"'), 'account popover action is not keyboard-addressable')
requireContract(appSource.includes("from 'lucide-react'"), 'shell icons must come from Lucide')
requireContract(appSource.includes('<Icon size={18} />'), 'navigation must render its Lucide icon component')
requireContract(!appSource.includes('<svg'), 'shell must not introduce custom SVG icons')
requireContract(appSource.includes('id="studio-search-results" className="studio-search-results" role="listbox"'), 'search results lack a stable listbox target')
requireContract(appSource.includes('aria-haspopup="listbox" aria-controls="studio-search-results" aria-expanded={searchOpen && Boolean(query.trim())} aria-autocomplete="list" aria-activedescendant={searchOpen && selectedSearchMatch ? `studio-search-option-${selectedSearchIndex}` : undefined}'), 'search input lacks active-descendant listbox semantics')
requireContract(appSource.includes("if (event.key === 'ArrowDown' || event.key === 'ArrowUp')"), 'search does not support arrow-key option navigation')
requireContract(appSource.includes("if (event.key === 'Escape')"), 'search does not support Escape dismissal')
requireContract(appSource.includes("if (event.key === 'Enter')"), 'search does not support Enter selection')
requireContract(appSource.includes('role="option" aria-selected={selectedSearchIndex === index}'), 'search results are missing selected option semantics')
requireContract(appSource.includes('id={`studio-search-option-${index}`}'), 'search options lack active-descendant ids')
requireContract(appSource.includes('data-accent={shellAccent}'), 'shell root lacks a route-derived data-accent marker')
requireContract(appSource.includes('function studioAccentForPath(pathname: string): StudioAccent'), 'shell accent mapping is missing')
requireRejected(
  appSource.replace("if (event.key === 'Escape')", "if (event.key === 'Dismiss')"),
  (source) => source.includes("if (event.key === 'Escape')"),
  'the search Escape handler was removed',
  'restore Escape dismissal in handleSearchKeyDown',
)
requireContract(!themeSource.includes('radial-gradient('), 'shell theme retains radial-gradient decoration')
requireContract(!themeSource.includes('.studio-brand-mark::after'), 'shell theme retains a decorative orb pseudo-element')

const mobileBlock = extractBlock(themeSource, '@media (max-width: 1120px)')
requireContract(mobileBlock.includes('.studio-sidebar'), 'mobile drawer selector is missing')
requireContract(mobileBlock.includes('width: min(292px, 84vw)'), 'mobile compact navigation did not restore the full-width drawer')
requireContract(mobileBlock.includes('transform: translateX(-102%)'), 'mobile drawer closed state is missing')
requireContract(mobileBlock.includes('.studio-sidebar.is-open'), 'mobile drawer open state is missing')
requireContract(mobileBlock.includes('.studio-workspace'), 'mobile workspace selector is missing')
requireContract(mobileBlock.includes('margin-left: 0'), 'mobile workspace offset was not restored')
requireRejected(
  mobileBlock.replace('margin-left: 0', 'margin-left: 56px'),
  (source) => source.includes('margin-left: 0'),
  'the <=1120px drawer workspace offset was changed',
  'restore margin-left: 0 inside @media (max-width: 1120px)',
)
const compactDesktopStart = themeSource.indexOf('@media (min-width: 1121px)')
const compactDesktopEnd = compactDesktopStart + desktopCompactBlock.length
const compactLabelSelectors = [
  '.studio-shell.is-compact-navigation .studio-brand-copy',
  '.studio-shell.is-compact-navigation .studio-nav-group > h2',
  '.studio-shell.is-compact-navigation .studio-nav-copy',
  '.studio-shell.is-compact-navigation .studio-account-copy',
] as const
const outsideCompactDesktop = themeSource.slice(0, compactDesktopStart) + themeSource.slice(compactDesktopEnd)
for (const selector of compactLabelSelectors) {
  requireContract(desktopCompactBlock.includes(selector), `compact label selector is missing: ${selector}`)
  requireContract(!mobileBlock.includes(selector), `mobile drawer must not hide compact label selector: ${selector}`)
  requireContract(!outsideCompactDesktop.includes(selector), `compact label selector escaped desktop scope: ${selector}`)
}

const topbarBlock = extractBlock(themeSource, '.studio-topbar')
const fallbackIndex = topbarBlock.indexOf('background: var(--mg-bg);')
const translucentIndex = topbarBlock.indexOf('background: color-mix(in srgb, var(--mg-bg) 91%, transparent);')
requireContract(fallbackIndex >= 0 && translucentIndex > fallbackIndex, 'topbar must place its opaque fallback before color-mix')
requireContract(topbarBlock.includes('backdrop-filter: blur(18px)'), 'topbar blur is missing')
requireContract(topbarBlock.includes('-webkit-backdrop-filter: blur(18px)'), 'topbar WebKit blur fallback is missing')

const letterSpacingValues = [...themeSource.matchAll(/letter-spacing\s*:\s*([^;]+);/g)].map((match) => match[1].trim())
requireContract(letterSpacingValues.length > 0, 'theme tracking declarations are missing')
requireContract(
  letterSpacingValues.every((value) => /^var\(--mg-track-(?:tight|normal|wide)\)$/.test(value)),
  'all theme tracking declarations must use zero-valued tracking tokens',
)
requireContract(!/letter-spacing\s*:\s*-/.test(themeSource), 'negative theme tracking remains')

const reducedMotionBlock = extractBlock(themeSource, '@media (prefers-reduced-motion: reduce)')
requireContract(themeSource.includes('animation: studio-pulse'), 'shell pulse animation coverage is missing')
requireContract(themeSource.includes('animation: studio-pop'), 'shell pop animation coverage is missing')
requireContract(reducedMotionBlock.includes('.studio-workspace-card i'), 'reduced motion does not cover shell pulse')
requireContract(reducedMotionBlock.includes('.studio-account-popover'), 'reduced motion does not cover shell pop')
requireContract(reducedMotionBlock.includes('animation: none'), 'reduced motion does not disable shell animations')
requireContract(reducedMotionBlock.includes('transition: none'), 'reduced motion does not disable shell transitions')
requireContract(reducedMotionBlock.includes('transform: none'), 'reduced motion does not disable hover transforms')
requireContract(
  !/(?:display|width|height|padding|margin|grid|position|inset|top|right|bottom|left)\s*:/.test(reducedMotionBlock),
  'reduced motion coverage must not change layout',
)

console.log('Media Studio shell contract passed: count-derived compact rail, accessible drawer restoration, topbar fallback/blur, tracking, and reduced motion')
