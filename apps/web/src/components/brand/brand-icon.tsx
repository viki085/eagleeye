import Image from "next/image";

interface BrandIconProps {
  /** Rendered size in px (the source is 160px, sharp up to 3x screens at 40px). */
  size?: number;
  className?: string;
}

/** The EagleEye app icon: the emblem on a dark warm tile. Decorative next to the name. */
export function BrandIcon({ size = 36, className = "" }: BrandIconProps) {
  return (
    <Image
      src="/brand/eagleeye-icon.png"
      alt=""
      aria-hidden="true"
      width={size}
      height={size}
      priority
      className={`shrink-0 rounded-lg ring-1 ring-[rgba(197,163,104,0.25)] ${className}`}
    />
  );
}
