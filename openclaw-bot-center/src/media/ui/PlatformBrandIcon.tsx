import type { CSSProperties } from "react";
import type { LucideIcon } from "lucide-react";
import {
  resolvePlatform,
  type PlatformIconSize,
  type PlatformInput,
} from "./platformRegistry";
import { classNames } from "./classNames";
import styles from "./PlatformBrandIcon.module.css";

export interface PlatformBrandIconProps {
  platform: PlatformInput;
  size?: PlatformIconSize;
  decorative?: boolean;
  className?: string;
}

const GLYPH_SIZE: Readonly<Record<PlatformIconSize, number>> = {
  sm: 16,
  md: 20,
  lg: 24,
};

const SIZE_CLASS: Readonly<Record<PlatformIconSize, string>> = {
  sm: styles.iconSm,
  md: styles.iconMd,
  lg: styles.iconLg,
};

interface SimpleIconGlyph {
  readonly path: string;
}

export function PlatformBrandIcon({
  platform,
  size = "md",
  decorative = false,
  className,
}: PlatformBrandIconProps) {
  const definition = resolvePlatform(platform);
  const glyphSize = GLYPH_SIZE[size];
  const accessibility = decorative
    ? { "aria-hidden": true as const }
    : {
        role: "img" as const,
        "aria-label": definition.accessibleName,
        title: definition.accessibleName,
      };
  const style = definition.brandColor
    ? ({ color: definition.brandColor } satisfies CSSProperties)
    : undefined;

  if (definition.iconSource.kind === "simple-icons") {
    const icon = definition.icon as SimpleIconGlyph;
    return (
      <span
        {...accessibility}
        className={classNames(styles.icon, SIZE_CLASS[size], className)}
        data-platform-icon=""
        data-platform-icon-size={size}
        data-platform-icon-source={definition.iconSource.exportName}
        data-platform-key={definition.key}
        style={style}
      >
        <svg
          aria-hidden="true"
          focusable="false"
          height={glyphSize}
          viewBox="0 0 24 24"
          width={glyphSize}
        >
          <path d={icon.path} fill="currentColor" />
        </svg>
      </span>
    );
  }

  const Icon = definition.icon as LucideIcon;
  return (
    <span
      {...accessibility}
      className={classNames(styles.icon, SIZE_CLASS[size], className)}
      data-platform-icon=""
      data-platform-icon-size={size}
      data-platform-icon-source={definition.iconSource.exportName}
      data-platform-key={definition.key}
    >
      <Icon aria-hidden="true" size={glyphSize} strokeWidth={1.8} />
    </span>
  );
}
