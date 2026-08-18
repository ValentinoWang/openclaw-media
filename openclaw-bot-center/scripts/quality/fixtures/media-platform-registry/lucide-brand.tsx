import { Tv } from "lucide-react";

export function PlatformIcon({ platform }: { platform: string }) {
  if (platform === "bilibili") return <Tv />;
  return null;
}
