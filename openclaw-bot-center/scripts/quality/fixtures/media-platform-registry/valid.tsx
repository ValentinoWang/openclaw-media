import { PlatformIdentity } from "../../../../../src/media/ui/PlatformIdentity";

export function ValidPlatform({ platform }: { platform: string }) {
  return <PlatformIdentity platform={platform} />;
}
