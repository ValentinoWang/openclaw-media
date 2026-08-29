import assert from "node:assert/strict";
import {
  getOrganizationDocumentUrl,
  ORGANIZATION_DOCUMENT_HOSTS,
} from "../../src/media/ui/organizationDocumentUrl";

assert.deepEqual(
  [...ORGANIZATION_DOCUMENT_HOSTS].sort(),
  ["feishu.cn", "larkoffice.com", "larksuite.com"],
  "organization document host allow-list must stay exactly Feishu/Lark",
);

// Valid docx URL passes through unchanged.
assert.equal(
  getOrganizationDocumentUrl({ organizationDocumentUrl: "https://xyz123.feishu.cn/docx/AbCdEfGh12345678" }),
  "https://xyz123.feishu.cn/docx/AbCdEfGh12345678",
  "a valid feishu.cn docx link must be accepted",
);

// Valid wiki URL on a larkoffice.com subdomain passes through unchanged.
assert.equal(
  getOrganizationDocumentUrl({ larkDocumentUrl: "https://team.larkoffice.com/wiki/AbCdEfGh12345678" }),
  "https://team.larkoffice.com/wiki/AbCdEfGh12345678",
  "a valid larkoffice.com wiki link on a subdomain must be accepted",
);

// larksuite.com apex domain passes.
assert.notEqual(
  getOrganizationDocumentUrl({ organizationDocumentUrl: "https://larksuite.com/docs/AbCdEfGh12345678" }),
  null,
  "the larksuite.com apex host must be accepted",
);

// organizationDocumentUrl takes precedence over larkDocumentUrl when both are present.
assert.equal(
  getOrganizationDocumentUrl({
    organizationDocumentUrl: "https://a.feishu.cn/docx/AbCdEfGh12345678",
    larkDocumentUrl: "https://b.feishu.cn/docx/ZzZzZzZz12345678",
  }),
  "https://a.feishu.cn/docx/AbCdEfGh12345678",
  "organizationDocumentUrl must take precedence over larkDocumentUrl",
);

// http:// (not https://) must be rejected -- this is the RunsPage regression this module fixes.
assert.equal(
  getOrganizationDocumentUrl({ organizationDocumentUrl: "http://evil.test/anything" }),
  null,
  "non-HTTPS links must be rejected",
);
assert.equal(
  getOrganizationDocumentUrl({ organizationDocumentUrl: "http://xyz123.feishu.cn/docx/AbCdEfGh12345678" }),
  null,
  "even an otherwise-valid Feishu path must be rejected over plain HTTP",
);

// A host that merely contains the allow-listed domain as a suffix of an
// attacker-controlled label must be rejected (domain confusion / lookalike host).
assert.equal(
  getOrganizationDocumentUrl({ organizationDocumentUrl: "https://feishu.cn.evil.example/docx/AbCdEfGh12345678" }),
  null,
  "a lookalike host must not be accepted just because it contains an allow-listed domain",
);
assert.equal(
  getOrganizationDocumentUrl({ organizationDocumentUrl: "https://evilfeishu.cn/docx/AbCdEfGh12345678" }),
  null,
  "a host that merely ends with the allow-listed domain's characters (without a dot boundary) must be rejected",
);

// A path with the wrong number of segments must be rejected.
assert.equal(
  getOrganizationDocumentUrl({ organizationDocumentUrl: "https://xyz123.feishu.cn/docx/AbCdEfGh12345678/extra" }),
  null,
  "a three-segment path must be rejected",
);
assert.equal(
  getOrganizationDocumentUrl({ organizationDocumentUrl: "https://xyz123.feishu.cn/docx" }),
  null,
  "a single-segment path must be rejected",
);

// An unsupported path kind must be rejected.
assert.equal(
  getOrganizationDocumentUrl({ organizationDocumentUrl: "https://xyz123.feishu.cn/sheets/AbCdEfGh12345678" }),
  null,
  "a path kind outside wiki/docx/doc/docs must be rejected",
);

// A token with illegal characters (or that is too short) must be rejected.
assert.equal(
  getOrganizationDocumentUrl({ organizationDocumentUrl: "https://xyz123.feishu.cn/docx/short" }),
  null,
  "a token shorter than 8 characters must be rejected",
);
assert.equal(
  getOrganizationDocumentUrl({ organizationDocumentUrl: "https://xyz123.feishu.cn/docx/has spaces here" }),
  null,
  "a token containing illegal characters must be rejected",
);
assert.equal(
  getOrganizationDocumentUrl({ organizationDocumentUrl: "https://xyz123.feishu.cn/docx/<script>alert(1)</script>" }),
  null,
  "a token containing markup characters must be rejected",
);

// A malformed URL must be rejected without throwing.
assert.equal(
  getOrganizationDocumentUrl({ organizationDocumentUrl: "not a url" }),
  null,
  "a malformed URL must be rejected rather than throwing",
);

// Missing / non-string values must be rejected.
assert.equal(getOrganizationDocumentUrl({}), null, "an artifact with no document URL fields must return null");
assert.equal(
  getOrganizationDocumentUrl({ organizationDocumentUrl: null, larkDocumentUrl: null }),
  null,
  "explicit null values must return null",
);

console.log("organization document URL validator: PASS");
