import { useState } from "react";
import { brand } from "./brand";

/** Official logo if present in /public/brand, otherwise a wordmark placeholder (dot mark + "Insight"). */
export function Logo({ light = true, size = 28 }: { light?: boolean; size?: number }) {
  const [failed, setFailed] = useState(false);
  if (!failed)
    return <img src={brand.logoUrl} alt={brand.company} height={size} onError={() => setFailed(true)} className="logo-img" />;
  const dots = [[0, 0], [1, 0], [0, 1], [1, 1], [2, 1], [1, 2], [0, 2]];
  return (
    <span className="wordmark" role="img" aria-label={`${brand.company} logo`} style={{ fontSize: size, color: light ? "#fff" : "#3a3a46" }}>
      <svg width={size * 0.62} height={size * 0.62} viewBox="0 0 12 12" aria-hidden style={{ marginRight: size * 0.12 }}>
        {dots.map(([x, y], i) => <circle key={i} cx={2 + x * 4} cy={2 + y * 4} r={1.35} fill={brand.colors.primary} />)}
      </svg>
      {brand.company}
    </span>
  );
}
