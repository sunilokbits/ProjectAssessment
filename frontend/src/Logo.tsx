import { useState } from "react";
import { brand } from "./brand";

/** Official logo if present in /public/brand, otherwise a text wordmark placeholder. */
export function Logo({ light = true, size = 28 }: { light?: boolean; size?: number }) {
  const [failed, setFailed] = useState(false);
  if (!failed)
    return <img src={brand.logoUrl} alt={brand.company} height={size} onError={() => setFailed(true)} className="logo-img" />;
  return (
    <span className="wordmark" role="img" aria-label={`${brand.company} logo`}
          style={{ fontSize: size, color: light ? "#fff" : brand.colors.ink }}>
      insight<span className="wordmark-dot" style={{ background: brand.colors.primary }} />
    </span>
  );
}
