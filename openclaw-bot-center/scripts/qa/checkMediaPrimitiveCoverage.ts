import { PRIMITIVES, formatSummary, inspectProject } from './checkMediaPrimitiveAdoption'

const MINIMUM_ADOPTION = 0.9
const report = inspectProject()

function validateSummaryShape() {
  const failures: string[] = []
  if (report.results.length !== report.surfaces || report.surfaces < 24) failures.push(`summary surfaces/results mismatch: ${report.surfaces}/${report.results.length}`)
  if (new Set(report.results.map((result) => result.id)).size !== report.results.length) failures.push('summary contains duplicate surface IDs')
  for (const primitive of PRIMITIVES) {
    const summary = report.primitives[primitive]
    const eligible = report.results.filter((result) => result.eligible.includes(primitive))
    const adopted = eligible.filter((result) => result.adopted.includes(primitive)).length
    const expectedPercentage = summary.eligible ? adopted / summary.eligible : 0
    if (summary.eligible !== eligible.length || summary.adopted !== adopted || Math.abs(summary.percentage - expectedPercentage) > Number.EPSILON) {
      failures.push(`summary ${primitive} is inconsistent with per-surface results`)
    }
    if (summary.adopted < 0 || summary.adopted > summary.eligible) failures.push(`summary ${primitive} has invalid adoption counts`)
    if (summary.exempt.length + summary.eligible !== report.surfaces) failures.push(`summary ${primitive} eligibility/exemption partition is incomplete`)
    if (summary.eligible > 0 && summary.percentage < MINIMUM_ADOPTION) failures.push(`coverage ${primitive}: ${(summary.percentage * 100).toFixed(1)}% is below ${(MINIMUM_ADOPTION * 100).toFixed(0)}%`)
  }
  for (const family of ['admin', 'ordinary'] as const) {
    for (const primitive of ['mg-btn', 'mg-tabs'] as const) {
      const expected = report.results.some((result) => result.family === family && result.adopted.includes(primitive)) ? 1 : 0
      if (report.familyCoverage[family][primitive] !== expected) failures.push(`summary ${family}.${primitive} is inconsistent with per-surface results`)
      if (!report.familyCoverage[family][primitive]) failures.push(`${family} family has no ${primitive} consumer`)
    }
  }
  return failures
}

const failures = [...validateSummaryShape(), ...report.violations]
for (const primitive of PRIMITIVES) {
  const summary = report.primitives[primitive]
  if (summary.percentage < MINIMUM_ADOPTION && !failures.some((failure) => failure.includes(`coverage ${primitive}:`))) failures.push(`coverage ${primitive}: ${(summary.percentage * 100).toFixed(1)}% is below ${(MINIMUM_ADOPTION * 100).toFixed(0)}%`)
}
console.log(`media primitive coverage: ${formatSummary(report)}`)
if (failures.length) {
  for (const failure of failures) console.error(`- ${failure}`)
  process.exitCode = 1
}
