import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { secureUuid } from '../../src/media/secureUuid'

const mediaSources = [
  'src/media/MediaApp.tsx',
  'src/media/MediaWebWorkspace.tsx',
  'src/media/mediaWebApi.ts',
  'src/media/secureUuid.ts',
]

for (const sourcePath of mediaSources) {
  const source = readFileSync(resolve(sourcePath), 'utf8')
  if (source.includes('crypto.randomUUID')) throw new Error(`${sourcePath} uses crypto.randomUUID`)
}

const ids = Array.from({ length: 10_000 }, secureUuid)
const canonicalV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
if (ids.some((id) => !canonicalV4.test(id))) throw new Error('secureUuid emitted a non-canonical UUID v4')
if (new Set(ids).size !== ids.length) throw new Error('secureUuid emitted a duplicate UUID')

console.log('secure UUID gate: PASS')
