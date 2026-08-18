export function PlatformName({ platform }: { platform: string }) {
  return <strong>{platform === "douyin" ? "抖音" : "小红书"}</strong>;
}
