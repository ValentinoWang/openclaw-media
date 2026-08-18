import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = readFileSync(resolve('src/media/CreationRunDetailPage.tsx'), 'utf8')

assert.match(source, /callBusinessOperation<RunResponse>\('getRun'/)
assert.match(source, /path:\s*\{\s*publicRunId:\s*runId\s*\}/)
assert.doesNotMatch(source, /loadMediaJobDetail|job_detail|job_id/)

console.log('media run detail route contract passed')
