import { CircleHelp, Globe2 } from "lucide-react";

export function GenericPlatformStates({ known }: { known: boolean }) {
  return known ? <Globe2 aria-label="网页" /> : <CircleHelp aria-label="其他平台" />;
}
