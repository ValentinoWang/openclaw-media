import fs from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '../..')
const invitesPath = path.join(root, 'src/media/pages/ordinary/InvitesPage.tsx')
const helperPath = path.join(root, 'src/lib/clipboard.ts')

function requireGate(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message)
}

function validateInvites(source: string): void {
  requireGate(/import \{ copyText \} from '\.\.\/\.\.\/\.\.\/lib\/clipboard'/u.test(source), 'InvitesPage does not use the shared clipboard helper')
  requireGate(/await copyText\(code\)/u.test(source), 'invite code is not copied through the shared helper')
  requireGate(!/navigator\.clipboard/u.test(source), 'InvitesPage bypasses the clipboard compatibility path')
  requireGate((source.match(/onClick=\{\(\) => void copyAffiliateCode\(/gu) ?? []).length === 1, 'invite code must expose exactly one copy control')
  requireGate(!/styles\.(?:actionRow|secondaryAction)/u.test(source), 'duplicate invite copy action remains rendered')
}

function validateHelper(source: string): void {
  requireGate(/navigator\.clipboard\?\.writeText/u.test(source), 'secure-context clipboard path is missing')
  requireGate(/document\.execCommand\('copy'\)/u.test(source), 'HTTP clipboard fallback is missing')
  requireGate(/if \(!copied\)/u.test(source), 'clipboard fallback result is not verified')
}

const invites = fs.readFileSync(invitesPath, 'utf8')
const helper = fs.readFileSync(helperPath, 'utf8')

let directClipboardRegressionRejected = false
try {
  validateInvites(invites.replace('await copyText(code)', 'await navigator.clipboard.writeText(code)'))
} catch (error) {
  directClipboardRegressionRejected = error instanceof Error && /shared helper|bypasses/u.test(error.message)
}
requireGate(directClipboardRegressionRejected, 'direct Clipboard API red fixture was accepted')

let duplicateCopyControlRejected = false
try {
  validateInvites(invites + '\nonClick={() => void copyAffiliateCode(')
} catch (error) {
  duplicateCopyControlRejected = error instanceof Error && /exactly one copy control/u.test(error.message)
}
requireGate(duplicateCopyControlRejected, 'duplicate copy control red fixture was accepted')

validateInvites(invites)
validateHelper(helper)

const releaseRoot = process.env.MEDIA_RELEASE_ROOT
if (releaseRoot) {
  const index = fs.readFileSync(path.join(releaseRoot, 'index.html'), 'utf8')
  const entryPath = index.match(/<script[^>]+src="\/openclaw\/media\/([^"]+\.js)"/u)?.[1]
  requireGate(entryPath, 'Media release entry script is missing')
  const bundle = fs.readFileSync(path.join(releaseRoot, entryPath), 'utf8')
  requireGate(bundle.includes('clipboard_copy_failed'), 'Media release is missing the verified clipboard fallback')
  requireGate(bundle.includes('已复制到剪贴板'), 'Media release is missing the invite copy success state')
}

console.log('invite clipboard compatibility gate passed')
