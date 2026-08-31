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

type NamedFunctionNode = ts.FunctionDeclaration | ts.FunctionExpression
type JsxNode = ts.JsxElement | ts.JsxSelfClosingElement
type JsxOpening = ts.JsxOpeningElement | ts.JsxSelfClosingElement

function findFunctionAnywhere(sourceFile: ts.SourceFile, name: string): NamedFunctionNode {
  let result: NamedFunctionNode | undefined
  function visit(node: ts.Node) {
    if ((ts.isFunctionDeclaration(node) || ts.isFunctionExpression(node)) && node.name?.text === name) result = node
    node.forEachChild(visit)
  }
  visit(sourceFile)
  requireContract(result, 'frontend function is missing: ' + name)
  return result
}

function findVariableDeclaration(sourceFile: ts.SourceFile, name: string): ts.VariableDeclaration {
  let result: ts.VariableDeclaration | undefined
  function visit(node: ts.Node) {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.name.text === name) result = node
    node.forEachChild(visit)
  }
  visit(sourceFile)
  requireContract(result, 'frontend variable is missing: ' + name)
  return result
}

function collectJsxNodes(root: ts.Node): JsxNode[] {
  const result: JsxNode[] = []
  function visit(node: ts.Node) {
    if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) result.push(node)
    node.forEachChild(visit)
  }
  visit(root)
  return result
}

function jsxOpening(node: JsxNode): JsxOpening {
  return ts.isJsxElement(node) ? node.openingElement : node
}

function jsxTagName(opening: JsxOpening): string {
  return opening.tagName.getText()
}

function jsxAttribute(opening: JsxOpening, name: string): ts.JsxAttribute | undefined {
  return opening.attributes.properties.find((property): property is ts.JsxAttribute => (
    ts.isJsxAttribute(property) && property.name.text === name
  ))
}

function jsxStringAttribute(opening: JsxOpening, name: string): string | null {
  const attribute = jsxAttribute(opening, name)
  return attribute?.initializer && ts.isStringLiteral(attribute.initializer) ? attribute.initializer.text : null
}

function jsxExpressionAttribute(opening: JsxOpening, name: string): ts.Expression | null {
  const attribute = jsxAttribute(opening, name)
  return attribute?.initializer && ts.isJsxExpression(attribute.initializer) ? attribute.initializer.expression ?? null : null
}

function containsIdentifier(root: ts.Node, name: string): boolean {
  let found = false
  function visit(node: ts.Node) {
    if (ts.isIdentifier(node) && node.text === name) found = true
    if (!found) node.forEachChild(visit)
  }
  visit(root)
  return found
}

function containsStringLiteral(root: ts.Node, value: string): boolean {
  let found = false
  function visit(node: ts.Node) {
    if (ts.isStringLiteral(node) && node.text === value) found = true
    if (!found) node.forEachChild(visit)
  }
  visit(root)
  return found
}

function collectCallExpressions(root: ts.Node): ts.CallExpression[] {
  const result: ts.CallExpression[] = []
  function visit(node: ts.Node) {
    if (ts.isCallExpression(node)) result.push(node)
    node.forEachChild(visit)
  }
  visit(root)
  return result
}

function callName(call: ts.CallExpression): string | null {
  return ts.isIdentifier(call.expression) ? call.expression.text : null
}

function containsCallTo(root: ts.Node, name: string): boolean {
  return collectCallExpressions(root).some((call) => callName(call) === name)
}

function containsMethodCall(root: ts.Node, name: string): boolean {
  return collectCallExpressions(root).some((call) => accessPropertyName(call.expression) === name)
}

function accessPropertyName(node: ts.Node): string | null {
  if (ts.isPropertyAccessExpression(node)) return node.name.text
  if (ts.isElementAccessExpression(node) && node.argumentExpression && ts.isStringLiteral(node.argumentExpression)) {
    return node.argumentExpression.text
  }
  return null
}

function accessReceiver(node: ts.Node): ts.Expression | null {
  if (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) return node.expression
  return null
}

function isNamedAccess(node: ts.Node, receiver: string, property: string): boolean {
  const target = accessReceiver(node)
  return accessPropertyName(node) === property && !!target && ts.isIdentifier(target) && target.text === receiver
}

function containsNamedPropertyAccess(root: ts.Node, receiver: string, property: string): boolean {
  let found = false
  function visit(node: ts.Node) {
    if (isNamedAccess(node, receiver, property)) found = true
    if (!found) node.forEachChild(visit)
  }
  visit(root)
  return found
}

function hasDirectClipboardWrite(sourceFile: ts.SourceFile): boolean {
  let found = false
  function visit(node: ts.Node) {
    if (accessPropertyName(node) === 'writeText') {
      const clipboardTarget = accessReceiver(node)
      const navigatorTarget = clipboardTarget ? accessReceiver(clipboardTarget) : null
      if (
        clipboardTarget
        && accessPropertyName(clipboardTarget) === 'clipboard'
        && navigatorTarget
        && ts.isIdentifier(navigatorTarget)
        && navigatorTarget.text === 'navigator'
      ) found = true
    }
    if (!found) node.forEachChild(visit)
  }
  visit(sourceFile)
  return found
}

function hasNamedImport(sourceFile: ts.SourceFile, moduleName: string, importedName: string, localName: string): boolean {
  return sourceFile.statements.some((statement) => {
    if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier) || statement.moduleSpecifier.text !== moduleName) return false
    const bindings = statement.importClause?.namedBindings
    if (!bindings || !ts.isNamedImports(bindings)) return false
    return bindings.elements.some((element) => (
      (element.propertyName?.text ?? element.name.text) === importedName && element.name.text === localName
    ))
  })
}

function stateUpdateStatus(call: ts.CallExpression): string | null {
  if (callName(call) !== 'setCopyState') return null
  const argument = call.arguments[0]
  if (!argument || !ts.isObjectLiteralExpression(argument)) return null
  const status = argument.properties.find((property) => propertyName(property) === 'status')
  if (!status || !ts.isPropertyAssignment(status) || !ts.isStringLiteral(status.initializer)) return null
  return status.initializer.text
}

function hasStateUpdate(root: ts.Node, status: string): boolean {
  return collectCallExpressions(root).some((call) => stateUpdateStatus(call) === status)
}

function collectTryStatements(root: ts.Node): ts.TryStatement[] {
  const result: ts.TryStatement[] = []
  function visit(node: ts.Node) {
    if (ts.isTryStatement(node)) result.push(node)
    node.forEachChild(visit)
  }
  visit(root)
  return result
}

function hasTemplateSuffix(expression: ts.Expression | null, identifier: string, suffix: string): boolean {
  if (!expression || !ts.isTemplateExpression(expression) || expression.templateSpans.length !== 1) return false
  const span = expression.templateSpans[0]
  return expression.head.text === ''
    && ts.isIdentifier(span.expression)
    && span.expression.text === identifier
    && span.literal.text === suffix
}

function numericValue(expression: ts.Expression): number | null {
  if (ts.isNumericLiteral(expression)) return Number(expression.text)
  if (ts.isPrefixUnaryExpression(expression) && expression.operator === ts.SyntaxKind.MinusToken && ts.isNumericLiteral(expression.operand)) {
    return -Number(expression.operand.text)
  }
  return null
}

function validateClipboardInteraction(sourceFile: ts.SourceFile): void {
  requireContract(hasNamedImport(sourceFile, '../../../lib/clipboard', 'copyText', 'copyText'), 'Admin Access must import the shared clipboard helper')
  requireContract(!hasDirectClipboardWrite(sourceFile), 'Admin Access directly bypasses the shared clipboard helper')

  const copyFunction = findFunctionAnywhere(sourceFile, 'copySafeCommand')
  const copyCalls = collectCallExpressions(copyFunction).filter((call) => callName(call) === 'copyText')
  requireContract(copyCalls.length === 1, 'safe-command copy must call the shared helper exactly once')
  const copyArgument = copyCalls[0]?.arguments[0]
  requireContract(!!copyArgument && isNamedAccess(copyArgument, 'item', 'safeCommand'), 'copy must be limited to item.safeCommand')

  const tryStatement = collectTryStatements(copyFunction).find((statement) => (
    collectCallExpressions(statement.tryBlock).some((call) => callName(call) === 'copyText')
  ))
  requireContract(tryStatement, 'copy operation is missing a try block')
  requireContract(!!tryStatement.catchClause, 'copy operation is missing rejected-promise handling')
  requireContract(hasStateUpdate(tryStatement.tryBlock, 'success'), 'copy success state is missing')
  requireContract(!!tryStatement.catchClause && hasStateUpdate(tryStatement.catchClause.block, 'error'), 'copy failure state is missing')

  const feedback = collectJsxNodes(sourceFile).some((node) => {
    const opening = jsxOpening(node)
    return jsxStringAttribute(opening, 'role') === 'status'
      && jsxStringAttribute(opening, 'aria-live') === 'polite'
      && containsNamedPropertyAccess(node, 'copyState', 'status')
  })
  requireContract(feedback, 'copy success/failure feedback lacks accessible status semantics')
}

function validateTabInteraction(sourceFile: ts.SourceFile): void {
  const tabMover = findFunctionAnywhere(sourceFile, 'moveTab')
  for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End']) {
    requireContract(containsStringLiteral(tabMover, key), 'primary tab mover must support ArrowLeft, ArrowRight, Home, and End')
  }
  requireContract(containsCallTo(tabMover, 'selectTab'), 'primary tab mover must update tab selection')
  requireContract(containsMethodCall(tabMover, 'focus'), 'primary tab mover must move focus')
  requireContract(containsMethodCall(tabMover, 'preventDefault'), 'primary tab mover must prevent browser scrolling')

  const tabNavigation = findVariableDeclaration(sourceFile, 'tabNavigation').initializer
  requireContract(!!tabNavigation && (ts.isJsxElement(tabNavigation) || ts.isJsxSelfClosingElement(tabNavigation)), 'primary tab navigation JSX is missing')
  const navigationNode = tabNavigation as ts.JsxElement | ts.JsxSelfClosingElement
  const tabDefinitions = findVariableDeclaration(sourceFile, 'tabs').initializer
  requireContract(!!tabDefinitions && ts.isArrayLiteralExpression(tabDefinitions) && tabDefinitions.elements.length === 3, 'primary tab definitions must contain three tabs')
  const tabButtons = collectJsxNodes(navigationNode).filter((node) => {
    const opening = jsxOpening(node)
    return jsxTagName(opening) === 'button' && jsxStringAttribute(opening, 'role') === 'tab' && !!jsxAttribute(opening, 'id')
  })
  requireContract(tabButtons.length === 1, 'primary tablist must map its three tab definitions')

  for (const node of tabButtons) {
    const opening = jsxOpening(node)
    const tabIndex = jsxExpressionAttribute(opening, 'tabIndex')
    requireContract(
      !!tabIndex
        && ts.isConditionalExpression(tabIndex)
        && numericValue(tabIndex.whenTrue) === 0
        && numericValue(tabIndex.whenFalse) === -1
        && containsIdentifier(tabIndex.condition, 'activeTab')
        && containsIdentifier(tabIndex.condition, 'key'),
      'primary tabs must use roving tabIndex with the active tab at zero',
    )
    const keyboardHandler = jsxExpressionAttribute(opening, 'onKeyDown')
    requireContract(!!keyboardHandler && containsCallTo(keyboardHandler, 'moveTab'), 'primary tabs are missing roving keyboard handling')
    requireContract(!!keyboardHandler && containsIdentifier(keyboardHandler, 'event') && containsIdentifier(keyboardHandler, 'key'), 'primary tab keyboard handler lacks its tab key context')
    const tabRef = jsxExpressionAttribute(opening, 'ref')
    requireContract(!!tabRef && containsIdentifier(tabRef, 'tabRefs'), 'primary tabs must register focusable refs')
    const selected = jsxExpressionAttribute(opening, 'aria-selected')
    requireContract(!!selected && containsIdentifier(selected, 'activeTab'), 'primary tabs must bind selection to activeTab')
    requireContract(hasTemplateSuffix(jsxExpressionAttribute(opening, 'id'), 'key', '-tab'), 'primary tab ids must be keyed')
    requireContract(hasTemplateSuffix(jsxExpressionAttribute(opening, 'aria-controls'), 'key', '-tabpanel'), 'primary tab controls must target keyed panels')
  }

  const panelBindings = collectJsxNodes(sourceFile)
    .filter((node) => jsxStringAttribute(jsxOpening(node), 'role') === 'tabpanel')
    .map((node) => ({
      id: jsxStringAttribute(jsxOpening(node), 'id'),
      labelledBy: jsxStringAttribute(jsxOpening(node), 'aria-labelledby'),
    }))
  for (const key of ['invitations', 'admission', 'registration']) {
    requireContract(panelBindings.some((panel) => panel.id === key + '-tabpanel' && panel.labelledBy === key + '-tab'), 'tabpanel binding is missing for ' + key)
  }

  const adminFunction = findFunction(sourceFile, 'AdminAccessPage')
  for (const [component, key] of [['InvitationTab', 'invitations'], ['AdmissionTab', 'admission'], ['RegistrationTab', 'registration']] as const) {
    const panel = collectJsxNodes(adminFunction).find((node) => jsxTagName(jsxOpening(node)) === component)
    requireContract(panel, component + ' is not rendered by the primary tab owner')
    const hidden = jsxExpressionAttribute(jsxOpening(panel), 'hidden')
    requireContract(!!hidden && containsIdentifier(hidden, 'activeTab') && containsStringLiteral(hidden, key), component + ' must remain bound to activeTab visibility')
  }
}

function validateFormLabelSemantics(sourceFile: ts.SourceFile): void {
  const fields = collectJsxNodes(sourceFile).filter((node) => jsxTagName(jsxOpening(node)) === 'Field')
  requireContract(fields.length > 0, 'Admin Access fields are missing')
  for (const field of fields) {
    const nestedNativeLabel = collectJsxNodes(field).some((node) => jsxTagName(jsxOpening(node)) === 'label')
    requireContract(!nestedNativeLabel, 'Field must not contain a nested native label')
  }
}

function validateEnhancedFrontend(source: string): void {
  const sourceFile = ts.createSourceFile(frontendPath, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  validateClipboardInteraction(sourceFile)
  validateTabInteraction(sourceFile)
  validateFormLabelSemantics(sourceFile)
}

function expectRejected(label: string, source: string, message: RegExp): void {
  let rejected = false
  try {
    validateEnhancedFrontend(source)
  } catch (error) {
    rejected = error instanceof Error && message.test(error.message)
  }
  requireContract(rejected, label + ' red fixture was accepted')
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

validateEnhancedFrontend(frontendSource)

if (process.argv.includes('--self-test')) {
  expectRejected(
    'direct clipboard bypass',
    frontendSource.replace('await copyText(item.safeCommand)', 'await navigator.clipboard.writeText(item.safeCommand)'),
    /shared clipboard helper|directly bypasses/u,
  )
  expectRejected(
    'missing copy failure handling',
    frontendSource.replace("setCopyState({ platform: item.platform, status: 'error' })", "setCopyState({ platform: item.platform, status: 'success' })"),
    /rejected-promise handling|failure state/u,
  )
  expectRejected(
    'missing roving tab order',
    frontendSource.replace('tabIndex={activeTab === key ? 0 : -1}', 'tabIndex={0}'),
    /roving tabIndex/u,
  )
  expectRejected(
    'missing roving keyboard semantics',
    frontendSource.replace('onKeyDown={(event) => moveTab(event, key)}', 'onKeyDown={() => undefined}'),
    /roving keyboard/u,
  )
  expectRejected(
    'nested form label',
    frontendSource.replace('<span className={styles.switchField}>', '<label className={styles.switchField}>').replace('</span></Field>', '</label></Field>'),
    /nested native label/u,
  )
  console.log('qa:media-admin-access-contract: PASS IF2 operations=8 plaintextCodes=0 selfTest=green redFixtures=5')
} else {
  console.log('qa:media-admin-access-contract: PASS IF2 operations=8 mutations=5 plaintextCodes=0')
}
