import { CircleHelp, Globe2, type LucideIcon } from "lucide-react";
import {
  siBilibili,
  siKuaishou,
  siSinaweibo,
  siTiktok,
  siWechat,
  siXiaohongshu,
  siZhihu,
  type SimpleIcon,
} from "simple-icons";

export const PLATFORM_KEYS = [
  "douyin",
  "xiaohongshu",
  "kuaishou",
  "bilibili",
  "wechat",
  "weibo",
  "zhihu",
  "web",
  "unknown",
] as const;

export type PlatformKey = (typeof PLATFORM_KEYS)[number];
export type BrandPlatformKey = Exclude<PlatformKey, "web" | "unknown">;
export type PlatformInput = string | null | undefined;
export type PlatformIconSize = "sm" | "md" | "lg";

export type PlatformIconSource =
  | Readonly<{
      kind: "simple-icons";
      exportName:
        | "siTiktok"
        | "siXiaohongshu"
        | "siKuaishou"
        | "siBilibili"
        | "siWechat"
        | "siSinaweibo"
        | "siZhihu";
      package: "simple-icons";
      version: "16.28.0";
      license: "CC0-1.0";
    }>
  | Readonly<{
      kind: "lucide";
      exportName: "Globe2" | "CircleHelp";
      package: "lucide-react";
    }>;

export interface PlatformDefinition {
  key: PlatformKey;
  aliases: readonly string[];
  label: string;
  accessibleName: string;
  isBrand: boolean;
  brandColor: `#${string}` | null;
  icon: SimpleIcon | LucideIcon;
  iconSource: PlatformIconSource;
}

export const PLATFORM_REGISTRY: Readonly<
  Record<PlatformKey, PlatformDefinition>
> = {
  douyin: {
    key: "douyin",
    aliases: ["douyin", "抖音"],
    label: "抖音",
    accessibleName: "抖音",
    isBrand: true,
    brandColor: "#000000",
    icon: siTiktok,
    iconSource: {
      kind: "simple-icons",
      exportName: "siTiktok",
      package: "simple-icons",
      version: "16.28.0",
      license: "CC0-1.0",
    },
  },
  xiaohongshu: {
    key: "xiaohongshu",
    aliases: ["xiaohongshu", "redbook", "小红书"],
    label: "小红书",
    accessibleName: "小红书",
    isBrand: true,
    brandColor: "#FF2442",
    icon: siXiaohongshu,
    iconSource: {
      kind: "simple-icons",
      exportName: "siXiaohongshu",
      package: "simple-icons",
      version: "16.28.0",
      license: "CC0-1.0",
    },
  },
  kuaishou: {
    key: "kuaishou",
    aliases: ["kuaishou", "快手"],
    label: "快手",
    accessibleName: "快手",
    isBrand: true,
    brandColor: "#FF4906",
    icon: siKuaishou,
    iconSource: {
      kind: "simple-icons",
      exportName: "siKuaishou",
      package: "simple-icons",
      version: "16.28.0",
      license: "CC0-1.0",
    },
  },
  bilibili: {
    key: "bilibili",
    aliases: ["bilibili", "b站", "哔哩哔哩"],
    label: "哔哩哔哩",
    accessibleName: "哔哩哔哩",
    isBrand: true,
    brandColor: "#00A1D6",
    icon: siBilibili,
    iconSource: {
      kind: "simple-icons",
      exportName: "siBilibili",
      package: "simple-icons",
      version: "16.28.0",
      license: "CC0-1.0",
    },
  },
  wechat: {
    key: "wechat",
    aliases: ["wechat", "微信"],
    label: "微信",
    accessibleName: "微信",
    isBrand: true,
    brandColor: "#07C160",
    icon: siWechat,
    iconSource: {
      kind: "simple-icons",
      exportName: "siWechat",
      package: "simple-icons",
      version: "16.28.0",
      license: "CC0-1.0",
    },
  },
  weibo: {
    key: "weibo",
    aliases: ["weibo", "sinaweibo", "微博"],
    label: "微博",
    accessibleName: "微博",
    isBrand: true,
    brandColor: "#E6162D",
    icon: siSinaweibo,
    iconSource: {
      kind: "simple-icons",
      exportName: "siSinaweibo",
      package: "simple-icons",
      version: "16.28.0",
      license: "CC0-1.0",
    },
  },
  zhihu: {
    key: "zhihu",
    aliases: ["zhihu", "知乎"],
    label: "知乎",
    accessibleName: "知乎",
    isBrand: true,
    brandColor: "#0084FF",
    icon: siZhihu,
    iconSource: {
      kind: "simple-icons",
      exportName: "siZhihu",
      package: "simple-icons",
      version: "16.28.0",
      license: "CC0-1.0",
    },
  },
  web: {
    key: "web",
    aliases: ["web", "网页"],
    label: "网页",
    accessibleName: "网页",
    isBrand: false,
    brandColor: null,
    icon: Globe2,
    iconSource: {
      kind: "lucide",
      exportName: "Globe2",
      package: "lucide-react",
    },
  },
  unknown: {
    key: "unknown",
    aliases: ["unknown", "未知平台", "未标注", "平台待确认"],
    label: "其他平台",
    accessibleName: "其他平台",
    isBrand: false,
    brandColor: null,
    icon: CircleHelp,
    iconSource: {
      kind: "lucide",
      exportName: "CircleHelp",
      package: "lucide-react",
    },
  },
};

export const BRANDED_PLATFORM_KEYS = Object.values(PLATFORM_REGISTRY)
  .filter((definition) => definition.isBrand)
  .map((definition) => definition.key) as readonly BrandPlatformKey[];

const PLATFORM_BY_ALIAS = new Map<string, PlatformDefinition>();
for (const definition of Object.values(PLATFORM_REGISTRY)) {
  for (const alias of [definition.key, ...definition.aliases]) {
    const normalizedAlias = alias.trim().toLowerCase();
    const existing = PLATFORM_BY_ALIAS.get(normalizedAlias);
    if (existing && existing.key !== definition.key) {
      throw new Error(
        `Platform alias ${JSON.stringify(normalizedAlias)} belongs to both ${existing.key} and ${definition.key}`,
      );
    }
    PLATFORM_BY_ALIAS.set(normalizedAlias, definition);
  }
}

export function resolvePlatform(value: PlatformInput): PlatformDefinition {
  const normalized = value?.trim().toLowerCase();
  return normalized
    ? (PLATFORM_BY_ALIAS.get(normalized) ?? PLATFORM_REGISTRY.unknown)
    : PLATFORM_REGISTRY.unknown;
}

export function platformDisplayLabel(value: PlatformInput): string {
  return resolvePlatform(value).label;
}
