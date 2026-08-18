import { Settings } from "lucide-react";

const sourceUrl = "https://example.com/posts/1";

export function GenericTool() {
  return <a href={sourceUrl}><Settings aria-hidden="true" />设置</a>;
}
