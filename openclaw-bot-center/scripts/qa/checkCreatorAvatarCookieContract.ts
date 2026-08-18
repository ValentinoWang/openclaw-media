import fs from 'node:fs'
import path from 'node:path'

const projectRoot = path.resolve(import.meta.dirname, '../..')
const tracksPath = path.join(projectRoot, 'src/media/pages/ordinary/TracksPage.tsx')
const capabilitySelectorPath = path.join(projectRoot, 'src/media/task-launch/CapabilitySelector.tsx')
const ordinaryRoot = path.join(projectRoot, 'src/media/pages/ordinary')
const adminRoot = path.join(projectRoot, 'src/media/pages/admin')

function requireContract(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message)
}

function tsxFiles(directory: string): string[] {
  return fs.readdirSync(directory, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith('.tsx'))
    .map((entry) => path.join(directory, entry.name))
}

const tracksSource = fs.readFileSync(tracksPath, 'utf8')
const capabilitySelectorSource = fs.readFileSync(capabilitySelectorPath, 'utf8')
const ordinarySource = tsxFiles(ordinaryRoot).map((file) => fs.readFileSync(file, 'utf8')).join('\n')
const adminSource = tsxFiles(adminRoot).map((file) => fs.readFileSync(file, 'utf8')).join('\n')

requireContract(
  /type CreatorSummary[\s\S]*?avatarUrl:\s*string \| null/.test(tracksSource),
  'CreatorSummary must carry nullable avatarUrl',
)
requireContract(
  tracksSource.includes('referrerPolicy="no-referrer"') || tracksSource.includes("referrerPolicy={'no-referrer'}"),
  'creator avatar image must set referrerPolicy=no-referrer',
)
requireContract(/<img[\s\S]*?onError=/.test(tracksSource), 'creator avatar image must have an onError fallback')
requireContract(/<img[\s\S]*?avatarUrl/.test(tracksSource), 'creator card must render avatarUrl')
requireContract(
  capabilitySelectorSource.includes('data-capability-id={item.capabilityId}'),
  'capability options must expose a stable capability id for production QA',
)

requireContract(!/cookie/i.test(ordinarySource), 'ordinary pages must not expose cookie controls or cookie copy')
requireContract(/cookie/i.test(adminSource), 'cookie controls must be owned by an admin page')

console.log('qa:creator-avatar-cookie-contract: PASS')
