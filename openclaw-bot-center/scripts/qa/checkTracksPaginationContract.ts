import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const pagePath = new URL("../../src/media/pages/ordinary/TracksPage.tsx", import.meta.url);
const pageSource = readFileSync(pagePath, "utf8");

// Red fixture: the former first-page-only request must stay rejected.
const legacyFirstPageOnly = 'loadList<TrackSummary>("listTracks", "赛道列表", { cursor: undefined, pageSize: 20 })';
assert.throws(
  () => assert.doesNotMatch(legacyFirstPageOnly, /\bcursor:\s*undefined\b/),
);
assert.doesNotMatch(pageSource, /\bcursor:\s*undefined\b/, "TracksPage must not hard-code the first cursor");
assert.match(pageSource, /const MAX_LIST_PAGES = 100;/);
for (const [operation, publicId] of [
  ["listTracks", "track.publicTrackId"],
  ["listCreators", "creator.publicCreatorId"],
  ["listTrackRelationships", "relationship.publicRelationshipId"],
  ["listOwnedAccounts", "account.publicAccountId"],
]) {
  assert.match(
    pageSource,
    new RegExp(`"${operation}"[\\s\\S]{0,260}${publicId.replace(".", "\\.")}`),
    `${operation} must use its stable public ID when merging pages`,
  );
}

const helperStart = pageSource.indexOf("const MAX_LIST_PAGES = 100;");
const helperEnd = pageSource.indexOf("function toResourceError");
assert.ok(helperStart >= 0 && helperEnd > helperStart, "pagination helper boundaries must exist");
const helperSource = pageSource.slice(helperStart, helperEnd);

type PageFetcher = (query: Record<string, unknown>, signal: AbortSignal) => Promise<unknown>;
const testGlobal = globalThis as typeof globalThis & { __tracksPageFetcher?: PageFetcher };
testGlobal.__tracksPageFetcher = async () => {
  throw new Error("test fetcher was not configured");
};
const moduleSource = `
type ListResponse<T> = { schemaVersion: string; revision: number; items: T[]; nextCursor: string | null };
const callBusinessOperation = async <T>(_operation: string, request: { query: Record<string, unknown>; signal: AbortSignal }): Promise<T> => globalThis.__tracksPageFetcher(request.query, request.signal);
${helperSource}
export { loadAllListPages };
`;
const compiled = ts.transpileModule(moduleSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const pagination = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`) as {
  loadAllListPages: <T>(
    operation: string,
    subject: string,
    query: Record<string, unknown>,
    signal: AbortSignal,
    publicId: (item: T) => string,
  ) => Promise<{ items: T[] }>;
};

const controller = new AbortController();
const calls: Array<{ query: Record<string, unknown>; signal: AbortSignal }> = [];
testGlobal.__tracksPageFetcher = async (query, signal) => {
  calls.push({ query, signal });
  return query.cursor === undefined
    ? { schemaVersion: "test", revision: 1, items: [{ id: "a" }, { id: "b" }], nextCursor: "cursor-2" }
    : { schemaVersion: "test", revision: 2, items: [{ id: "b" }, { id: "c" }], nextCursor: null };
};
const merged = await pagination.loadAllListPages<{ id: string }>(
  "listTracks",
  "赛道列表",
  { pageSize: 20 },
  controller.signal,
  (item) => item.id,
);
assert.deepEqual(merged.items.map((item) => item.id), ["a", "b", "c"]);
assert.deepEqual(calls.map(({ query }) => query.cursor), [undefined, "cursor-2"]);
assert.ok(calls.every(({ signal }) => signal === controller.signal), "every page must receive the original AbortSignal");

testGlobal.__tracksPageFetcher = async () => ({ schemaVersion: "test", revision: 1, items: [], nextCursor: "" });
await assert.rejects(
  () => pagination.loadAllListPages("listTracks", "赛道列表", {}, controller.signal, () => "item"),
  /空分页游标/,
);

testGlobal.__tracksPageFetcher = async () => ({ schemaVersion: "test", revision: 1, items: [], nextCursor: "repeat" });
await assert.rejects(
  () => pagination.loadAllListPages("listTracks", "赛道列表", {}, controller.signal, () => "item"),
  /分页游标重复/,
);

testGlobal.__tracksPageFetcher = async () => ({ schemaVersion: "test", revision: 1, items: [{ id: "" }], nextCursor: null });
await assert.rejects(
  () => pagination.loadAllListPages<{ id: string }>("listTracks", "赛道列表", {}, controller.signal, (item) => item.id),
  /缺少公共标识/,
);

let pageNumber = 0;
testGlobal.__tracksPageFetcher = async () => {
  pageNumber += 1;
  return { schemaVersion: "test", revision: pageNumber, items: [], nextCursor: `cursor-${pageNumber}` };
};
await assert.rejects(
  () => pagination.loadAllListPages("listTracks", "赛道列表", {}, controller.signal, () => "item"),
  /超过 100 页上限/,
);

console.log("tracks pagination contract: red fixture rejected; cursor continuation, dedupe, AbortSignal, empty/repeated cursor, and page cap passed");
delete testGlobal.__tracksPageFetcher;
