import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, errorText } from "./api";

// ------------------------------------------------------------------ toasts
type Toast = { id: number; text: string; tone: "ok" | "err" | "info" };
const ToastCtx = createContext<(text: string, tone?: Toast["tone"]) => void>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: Toast["tone"] = "ok") => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { id, text, tone }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 3800);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast toast-${t.tone}`}>{t.tone === "ok" ? "✓ " : t.tone === "err" ? "⚠ " : ""}{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

/** Animated count-up for hero numbers. */
export function CountUp({ value, suffix = "", decimals = 0 }: { value: number | null | undefined; suffix?: string; decimals?: number }) {
  const [v, setV] = useState(0);
  const raf = useRef(0);
  useEffect(() => {
    if (value == null) return;
    const start = performance.now(), from = 0, dur = 900;
    const step = (t: number) => {
      const p = Math.min(1, (t - start) / dur);
      setV(from + (value - from) * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
  }, [value]);
  if (value == null) return <>–</>;
  return <>{v.toFixed(decimals)}{suffix}</>;
}

export function ragState(score: number | null | undefined, t = { green: 75, amber: 50 }) {
  if (score == null) return { state: "grey", label: "Not assessed", icon: "○" };
  if (score >= t.green) return { state: "green", label: "Green – on track", icon: "●" };
  if (score >= t.amber) return { state: "amber", label: "Amber – attention", icon: "▲" };
  return { state: "red", label: "Red – at risk", icon: "■" };
}

/** Meter row: name, bar, figure + status label (status never colour-only). */
export function Meter({ label, value, onClick, active, sub }: { label: ReactNode; value: number | null | undefined; onClick?: () => void; active?: boolean; sub?: ReactNode }) {
  const r = ragState(value);
  return (
    <div className={`meter ${onClick ? "clickable" : ""} ${active ? "active" : ""}`} onClick={onClick} role={onClick ? "button" : undefined}
         tabIndex={onClick ? 0 : undefined} onKeyDown={(e) => onClick && (e.key === "Enter" || e.key === " ") && onClick()}>
      <div className="meter-label">{label}{sub && <div className="small muted">{sub}</div>}</div>
      <div className="meter-track"><div className={`meter-fill rag-bg-${r.state}`} style={{ width: `${value ?? 0}%` }} /></div>
      <div className="meter-fig">{value == null ? "–" : `${value.toFixed(0)}%`}</div>
      <div className={`meter-status st-${r.state}`}><span aria-hidden>{r.icon}</span> {r.label.split(" – ")[0]}</div>
    </div>
  );
}

export function useApi<T = any>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setLoading(true);
    api
      .get<T>(path)
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e) => alive && setError(errorText(e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick, ...deps]);
  return { data, error, loading, reload: () => setTick((t) => t + 1), setData };
}

const ORIGIN_CLASS: Record<string, string> = {
  GLOBAL: "o-global",
  INDUSTRY: "o-industry",
  "SUB-DOMAIN": "o-sub",
  TECHNOLOGY: "o-tech",
  PROJECT: "o-project",
  "AI-DISCOVERED": "o-ai",
};
export function Origin({ origin }: { origin: string }) {
  return <span className={`badge ${ORIGIN_CLASS[origin] || ""}`}>{origin}</span>;
}

export function Rag({ rag, score }: { rag: { state: string; label: string }; score?: number | null }) {
  return (
    <span className={`rag rag-${rag.state}`} title={rag.label}>
      <span className="dot" aria-hidden />
      {score != null && <strong>{score.toFixed(0)}%</strong>} {rag.label}
    </span>
  );
}

export function Source({ s }: { s: any }) {
  if (!s) return null;
  return (
    <span className="muted small">
      {s.pack_name || s.pack_key}
      {s.pack_version ? ` v${s.pack_version}` : ""}
      {s.role ? ` · ${s.role}` : ""}
      {s.sub_domain ? ` · ${s.sub_domain}` : ""}
    </span>
  );
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return <pre className="error">{error}</pre>;
}

export function Card({ title, children, actions }: { title?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-h">
          <h3>{title}</h3>
          <div>{actions}</div>
        </header>
      )}
      {children}
    </section>
  );
}

export function Pill({ children, tone = "" }: { children: ReactNode; tone?: string }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

export function Bar({ value }: { value: number | null | undefined }) {
  const v = value ?? 0;
  const state = value == null ? "grey" : v >= 75 ? "green" : v >= 50 ? "amber" : "red";
  return (
    <div className="bar" role="meter" aria-valuenow={v} aria-valuemin={0} aria-valuemax={100}>
      <div className={`bar-fill rag-bg-${state}`} style={{ width: `${v}%` }} />
    </div>
  );
}

export function MultiCheck({
  options,
  value,
  onChange,
  columns = 3,
}: {
  options: { key: string; name: string; hint?: string }[];
  value: string[];
  onChange: (v: string[]) => void;
  columns?: number;
}) {
  return (
    <div className="checks" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
      {options.map((o) => (
        <label key={o.key} className="check" title={o.hint}>
          <input
            type="checkbox"
            checked={value.includes(o.key)}
            onChange={(e) => onChange(e.target.checked ? [...value, o.key] : value.filter((x) => x !== o.key))}
          />
          {o.name}
        </label>
      ))}
    </div>
  );
}

export function pct(v: number | null | undefined) {
  return v == null ? "–" : `${v.toFixed(0)}%`;
}
