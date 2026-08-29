import assert from "node:assert/strict";
import { MediaProductHttpError, MediaProductHttpTransport } from "../../src/media/mediaProductHttpTransport";

function failedFetch(payload: unknown, status = 500): typeof fetch {
  return async () => new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

async function readError(fetchImpl: typeof fetch): Promise<MediaProductHttpError> {
  try {
    await new MediaProductHttpTransport({ fetchImpl }).request("archive_list", {
      method: "GET",
      path: "/archives",
      query: {},
      authSource: "session",
      ownerRule: "tenant",
      idempotency: "none",
    });
  } catch (error) {
    assert.ok(error instanceof MediaProductHttpError);
    return error;
  }
  throw new Error("request must fail");
}

const hidden = await readError(failedFetch({ error: { code: "internal_error", message: "database stack trace" } }));
assert.equal(hidden.code, "internal_error");
assert.equal(hidden.message, "服务请求未完成。");
assert.doesNotMatch(hidden.message, /database stack trace/);

const known = await readError(failedFetch({ error: { code: "forbidden", message: "not permitted" } }, 403));
assert.equal(known.message, "当前账号没有此操作权限。");

const localized = await readError(failedFetch({ error: { code: "custom_error", message: "暂时无法读取，请稍后再试。" } }));
assert.equal(localized.message, "暂时无法读取，请稍后再试。");

console.log("media error isolation checks passed");
