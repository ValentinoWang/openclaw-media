import fs from 'node:fs'
import path from 'node:path'
import ts from 'typescript'

const projectRoot = path.resolve(import.meta.dirname, '../..')
const frontendPath = path.join(projectRoot, 'src/media/pages/admin/AdminAccessPage.tsx')

function requireContract(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message)
}

function sorted(values: Iterable<string>) {
  return [...values].sort()
}

function sameKeys(actual: Iterable<string>, expected: Iterable<string>) {
  return JSON.stringify(sorted(actual)) === JSON.stringify(sorted(expected))
}

function findFunction(sourceFile: ts.SourceFile, name: string) {
  let result: ts.FunctionDeclaration | undefined
  sourceFile.forEachChild((node) => {
    if (ts.isFunctionDeclaration(node) && node.name?.text === name) result = node
  })
  requireContract(result, `frontend function is missing: ${name}`)
  return result
}

function propertyName(node: ts.ObjectLiteralElementLike) {
  if (!('name' in node) || !node.name) return null
  if (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name) || ts.isNumericLiteral(node.name)) return node.name.text
  return null
}

function bodyKeySets(fn: ts.FunctionDeclaration) {
  const sets: Set<string>[] = []
  function visit(node: ts.Node) {
    if (
      ts.isVariableDeclaration(node)
      && ts.isIdentifier(node.name)
      && node.name.text === 'body'
      && node.initializer
      && ts.isObjectLiteralExpression(node.initializer)
    ) {
      sets.push(new Set(node.initializer.properties.map(propertyName).filter((name): name is string => !!name)))
    }
    node.forEachChild(visit)
  }
  fn.forEachChild(visit)
  requireContract(sets.length > 0, `body declaration is missing in ${fn.name?.text ?? 'anonymous function'}`)
  return sets
}

function requireKeySet(sets: Set<string>[], expected: string[], message: string) {
  const match = sets.find((keys) => sameKeys(keys, expected))
  requireContract(match, `${message}: expected=${sorted(expected).join(',')} actual=${sets.map((keys) => sorted(keys).join(',')).join(' | ')}`)
}

const frontendSource = fs.readFileSync(frontendPath, 'utf8')
const sourceFile = ts.createSourceFile(frontendPath, frontendSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)

requireContract(!frontendSource.includes('准入码仅显示一次'), 'retired one-time admission-code display remains')
requireContract(!frontendSource.includes('刷新页面后不会再次读取'), 'retired non-persistent admission-code copy remains')
requireContract(frontendSource.includes('已写入，并已从服务端重新读取。'), 'shared persistent write-readback copy is missing')
requireContract(!frontendSource.includes("stringField(object, 'code')"), 'B11 must not parse or expose plaintext admission codes')
requireContract(
  frontendSource.includes("assertExactKeys(object, ['batchId', 'name', 'status', 'codeCount', 'usedCount', 'expiresAt', 'createdAt']"),
  'IF2 admission batch parser fields drifted',
)
requireContract(frontendSource.includes('<colgroup><col className={styles.batchNameColumn}'), 'admission batch table is missing its explicit column grid')
requireContract((frontendSource.match(/<th className=\{styles\.numericCell\}/g) ?? []).length === 2, 'admission batch numeric headers must align with quota and used cells')
requireContract(frontendSource.includes('<th className={styles.actionCell}'), 'admission batch action header is not aligned with its cells')

for (const operationId of [
  'listAdminAffiliateUsers',
  'updateAdminAffiliateUser',
  'listAdminAdmissionBatches',
  'createAdminAdmissionBatch',
  'disableAdminAdmissionBatch',
  'getAdminRegistrationPolicy',
  'updateAdminRegistrationPolicy',
  'revokeAdminUserSessions',
]) {
  requireContract(frontendSource.includes(`'${operationId}'`), `generated B11 operation is not used: ${operationId}`)
}

const invitationBodies = bodyKeySets(findFunction(sourceFile, 'InvitationInspector'))
requireKeySet(invitationBodies, ['affiliateEnabled', 'invitationQuota', 'reason', 'expectedRevision'], 'affiliate update body drifted')
requireKeySet(invitationBodies, ['reason'], 'session revoke body drifted')

const admissionBodies = bodyKeySets(findFunction(sourceFile, 'AdmissionActions'))
requireKeySet(admissionBodies, ['name', 'codeCount', 'reason'], 'admission create body drifted')
requireKeySet(admissionBodies, ['reason', 'expectedRevision'], 'admission disable body drifted')

const registrationBodies = bodyKeySets(findFunction(sourceFile, 'RegistrationTab'))
requireKeySet(registrationBodies, ['mode', 'reason', 'expectedRevision'], 'registration policy body drifted')

console.log('qa:media-admin-access-contract: PASS IF2 operations=8 mutations=5 plaintextCodes=0')
