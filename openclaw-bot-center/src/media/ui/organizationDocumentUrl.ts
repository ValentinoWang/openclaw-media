/**
 * Shared validator for organization (Feishu/Lark) document links surfaced as
 * "打开组织文档" external links across the media web ordinary pages.
 *
 * This consolidates two independently-written implementations
 * (OverviewPage.tsx and RunsPage.tsx) that had drifted apart: the RunsPage
 * copy only checked for an http(s):// prefix, so any
 * `http://evil.test/anything` value would render as a clickable external
 * link. This module carries the stricter, allow-listed check and is now the
 * single source of truth for both pages.
 */
import { isPublicId } from "../identifiers";

/** Organization document hosts (and their subdomains) allowed to be linked out to. */
export const ORGANIZATION_DOCUMENT_HOSTS = [
  "feishu.cn",
  "larksuite.com",
  "larkoffice.com",
] as const;

export type DocumentLinkedArtifact = {
  organizationDocumentUrl?: string | null;
  larkDocumentUrl?: string | null;
};

export function getOrganizationDocumentUrl(artifact: DocumentLinkedArtifact): string | null {
  const value = artifact.organizationDocumentUrl ?? artifact.larkDocumentUrl;
  if (typeof value !== "string") return null;
  try {
    const parsed = new URL(value.trim());
    const validHost = ORGANIZATION_DOCUMENT_HOSTS.some(
      (host) => parsed.hostname === host || parsed.hostname.endsWith("." + host),
    );
    const parts = parsed.pathname.split("/").filter(Boolean);
    if (
      parsed.protocol !== "https:" ||
      !validHost ||
      parts.length !== 2 ||
      !["wiki", "docx", "doc", "docs"].includes(parts[0].toLowerCase()) ||
      !isPublicId(parts[1])
    ) return null;
    return parsed.toString();
  } catch {
    return null;
  }
}
