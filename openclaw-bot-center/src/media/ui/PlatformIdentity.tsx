import {
  resolvePlatform,
  type PlatformIconSize,
  type PlatformInput,
} from "./platformRegistry";
import { PlatformBrandIcon } from "./PlatformBrandIcon";
import styles from "./PlatformBrandIcon.module.css";

export interface PlatformIdentityProps {
  platform: PlatformInput;
  size?: PlatformIconSize;
  className?: string;
}

const SIZE_CLASS: Readonly<Record<PlatformIconSize, string>> = {
  sm: styles.identitySm,
  md: styles.identityMd,
  lg: styles.identityLg,
};

function classNames(...values: Array<string | undefined>): string {
  return values.filter(Boolean).join(" ");
}

export function PlatformIdentity({
  platform,
  size = "md",
  className,
}: PlatformIdentityProps) {
  const definition = resolvePlatform(platform);
  return (
    <span
      className={classNames(styles.identity, SIZE_CLASS[size], className)}
      data-platform-identity=""
      data-platform-key={definition.key}
    >
      <PlatformBrandIcon decorative platform={definition.key} size={size} />
      <span className={styles.label} data-platform-label="">
        {definition.label}
      </span>
    </span>
  );
}
