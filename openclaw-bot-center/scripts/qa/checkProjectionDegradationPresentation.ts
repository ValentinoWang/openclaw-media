import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const root = path.resolve(import.meta.dirname, "../..");

function read(relativePath: string): string {
  return fs.readFileSync(path.join(root, relativePath), "utf8");
}

function requireGate(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function directlyRenderedBackendFields(
  relativePath: string,
  source: string,
): string[] {
  const tree = ts.createSourceFile(
    relativePath,
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const renderedFields: string[] = [];
  const owners = new Set(["track", "account", "creator", "item"]);
  const fields = new Set([
    "status",
    "platform",
    "operationalStatus",
    "dataSource",
    "creatorRole",
    "role",
  ]);

  const unwrap = (expression: ts.Expression): ts.Expression => {
    if (
      ts.isParenthesizedExpression(expression) ||
      ts.isAsExpression(expression) ||
      ts.isNonNullExpression(expression)
    ) {
      return unwrap(expression.expression);
    }
    return expression;
  };

  const visit = (node: ts.Node) => {
    if (
      ts.isJsxExpression(node) &&
      node.expression &&
      (ts.isJsxElement(node.parent) || ts.isJsxFragment(node.parent))
    ) {
      const expression = unwrap(node.expression);
      if (
        ts.isPropertyAccessExpression(expression) &&
        ts.isIdentifier(expression.expression) &&
        owners.has(expression.expression.text) &&
        fields.has(expression.name.text)
      ) {
        const line = tree.getLineAndCharacterOfPosition(expression.getStart(tree)).line + 1;
        renderedFields.push(`${relativePath}:${line}:${expression.getText(tree)}`);
      }
    }
    ts.forEachChild(node, visit);
  };

  visit(tree);
  return renderedFields;
}

const tracks = read("src/media/pages/ordinary/TracksPage.tsx");
const invites = read("src/media/pages/ordinary/InvitesPage.tsx");
const overview = read("src/media/pages/ordinary/OverviewPage.tsx");
const ordinaryPages = [
  "src/media/pages/ordinary/ArchivesPage.tsx",
  "src/media/pages/ordinary/AssetsPage.tsx",
  "src/media/pages/ordinary/DecisionsPage.tsx",
  "src/media/pages/ordinary/InvitesPage.tsx",
  "src/media/pages/ordinary/MediaAgentPage.tsx",
  "src/media/pages/ordinary/OverviewPage.tsx",
  "src/media/pages/ordinary/PublishingPage.tsx",
  "src/media/pages/ordinary/ReviewsPage.tsx",
  "src/media/pages/ordinary/RunsPage.tsx",
  "src/media/pages/ordinary/TracksPage.tsx",
  "src/media/pages/ordinary/UsageBillingPage.tsx",
].map((relativePath) => [relativePath, read(relativePath)] as const);
const b02 = read("scripts/qa/captureB02TracksFullShell.ts");

for (const [label, source, legacyCopy] of [
  ["tracks", tracks, "部分业务投影暂时不可用，已返回的数据仍保持可见。"],
  ["invites", invites, "部分邀请数据暂时不可用，已返回的服务端结果仍保持可见。"],
  ["overview", overview, "部分运营汇总数据暂不可用，页面没有用其它数据源替代。"],
] as const) {
  requireGate(!source.includes(legacyCopy), `${label} still hides the failed resource behind generic partial copy`);
  requireGate(source.includes("data-page-partial"), `${label} lacks an observable partial-state surface`);
  requireGate(source.includes("重新读取") || source.includes("刷新并重新读取"), `${label} partial state has no retry action`);
}

const independentTrackLoads = [
  /loadList<TrackSummary>\([\s\S]{0,320}?"listTracks"[\s\S]{0,320}?setTrackState/,
  /loadList<CreatorSummary>\([\s\S]{0,320}?"listCreators"[\s\S]{0,320}?setCreatorState/,
  /loadList<TrackRelationship>\([\s\S]{0,320}?"listTrackRelationships"[\s\S]{0,320}?setRelationshipState/,
  /loadList<OwnedAccountSummary>\([\s\S]{0,320}?"listOwnedAccounts"[\s\S]{0,320}?setAccountState/,
];
requireGate(
  tracks.includes('"账号归属"') &&
    tracks.includes("以下资源读取失败") &&
    tracks.includes("已成功返回的资源仍保留在当前页面。") &&
    independentTrackLoads.every((pattern) => pattern.test(tracks)),
  "tracks must load each projection independently, name failures, and retain successful resources",
);
requireGate(
  !tracks.includes("Promise.all(["),
  "tracks detail aggregation must not discard one successful response when its sibling fails",
);
requireGate(
  b02.includes("the named failed projection resource") &&
    b02.includes("the successful tracks projection beside the failure"),
  "B02 browser fixture does not prove named failure plus retained successful data",
);

for (const [relativePath, source] of ordinaryPages) {
  requireGate(
    !/(?<![.\w])error\.message|(?<![.\w])reason\.message|instanceof Error\s*\?\s*(?:error|reason)\.message/.test(source),
    `${relativePath} may expose a backend error message to an ordinary user`,
  );
}

for (const [label, relativePath, source] of [[
  "ordinary tracks",
  "src/media/pages/ordinary/TracksPage.tsx",
  tracks,
]] as const) {
  const renderedBackendFields = directlyRenderedBackendFields(relativePath, source);
  requireGate(
    renderedBackendFields.length === 0,
    `${label} directly renders a backend enum or platform key: ${renderedBackendFields.join(", ")}`,
  );
  requireGate(
    source.includes("PlatformIdentity")
      && source.includes("operationalStatusDisplayLabel")
      && source.includes("ownedAccountDataSourceDisplayLabel"),
    `${label} lacks the shared Chinese presentation mapping for account data`,
  );
  requireGate(
    !source.includes("platformDisplayLabel"),
    `${label} must use PlatformIdentity instead of a platform label compatibility query`,
  );
}

for (const retiredOwnedAccountCopy of [
  "待授权",
  "等待授权",
  "授权异常",
  "重新授权",
  "授权状态",
  "OAuth",
  "oauth",
  "同步操作接口尚未开放",
  "编辑操作接口尚未开放",
  "停用操作接口尚未开放",
]) {
  requireGate(
    !tracks.includes(retiredOwnedAccountCopy),
    `owned-account ledger still exposes retired placeholder copy: ${retiredOwnedAccountCopy}`,
  );
}
for (const ledgerSection of ["账号身份", "组织责任", "运营定位", "运营状态", "数据状态"]) {
  requireGate(
    tracks.includes(ledgerSection),
    `owned-account ledger lacks the ${ledgerSection} section`,
  );
}

requireGate(
  !invites.includes("{item.status}"),
  "invites directly renders the backend invite status",
);
requireGate(
  invites.includes("inviteStatusDisplayLabel"),
  "invites lacks a Chinese fallback label for invite statuses",
);

console.log("projection degradation presentation: PASS");
