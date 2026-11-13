import { ReactNode, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, errorText, getUser } from "../api";
import { brand } from "../brand";
import { Card, CountUp, ErrorBox, Meter, ragState, useApi, useToast } from "../components";

const GROUPS: [string, string][] = [["business", "Business"], ["data", "Data"], ["architecture", "Architecture"],
  ["security", "Security"], ["domain", "Industry"], ["technology", "Technology"], ["delivery", "Delivery"]];

type Tip = { x: number; y: number; body: ReactNode } | null;

const LAUNCH_GROUPS = [{ key: "all", label: "All" }, { key: "assess", label: "Assessment" }, { key: "insight", label: "Insights" }, { key: "admin", label: "Administration" }];
const LAUNCH = [
  { group: "assess", tone: "t-blue", icon: "▤", title: "New Assessment", desc: "Create a client assessment and classify its domain", cta: "Create", to: "/assessments" },
  { group: "assess", tone: "t-green", icon: "✦", title: "Domain Auto-Detection", desc: "Upload an RFP / BRD and let AI suggest industry & technology", cta: "Detect", to: "/assessments" },
  { group: "assess", tone: "t-orange", icon: "?", title: "Tailored Questionnaire", desc: "Global + industry + technology + project questions, de-duplicated", cta: "Answer", to: "/assessments" },
  { group: "insight", tone: "t-pink", icon: "▦", title: "Readiness Heatmap", desc: "Green / Amber / Red readiness for every project and area", cta: "View", to: "#heatmap" },
  { group: "insight", tone: "t-purple", icon: "⚖", title: "Compliance Pipeline", desc: "Regulations suggested, confirmed and verified by reviewers", cta: "Review", to: "#compliance" },
  { group: "insight", tone: "t-cyan", icon: "◆", title: "Industry Coverage", desc: "24 industry domain packs with sub-domains, risks and KPIs", cta: "Explore", to: "#industries" },
  { group: "admin", tone: "t-blue", icon: "⚙", title: "Domain Management", desc: "Create, version and publish domain packs without code", cta: "Manage", to: "/admin/domains" },
  { group: "admin", tone: "t-green", icon: "⟳", title: "How to use", desc: "Step-by-step guide, roles, legends and FAQ", cta: "Learn", to: "/guide" },
];

const CAPABILITIES = [
  { i: "◆", t: "24 industry domain packs", d: "Banking to Aerospace: each pack brings its own questions, risks, KPIs, regulations, terminology and architecture patterns. No generic questionnaire." },
  { i: "⧉", t: "Four-layer questionnaire", d: "Global + Industry + Sub-domain + Technology + Project + AI-discovered questions, de-duplicated, with the origin of every question shown." },
  { i: "✦", t: "AI auto-detection, human confirmed", d: "Upload an RFP and the platform suggests industry, sub-domain, technology and project type with confidence – never locking the client in." },
  { i: "⚖", t: "Compliance without false claims", d: "Regulations are only ever 'potentially applicable' until an authorised reviewer confirms – verification requires evidence." },
  { i: "▥", t: "Transparent, comparable scoring", d: "A comparable overall score across every project, plus domain-adjusted readiness. Every weight is visible." },
  { i: "⟳", t: "Expand without code", d: "A new industry is a new YAML domain pack: validate, publish, selectable. Assessments keep the pack version they started with." },
];

export default function Showcase() {
  const { data, error, reload } = useApi<any>("/api/portfolio");
  const [tip, setTip] = useState<Tip>(null);
  const [rankBy, setRankBy] = useState<"comparable" | "domain_adjusted">("comparable");
  const [ind, setInd] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [launchFilter, setLaunchFilter] = useState("all");
  const launchCards = launchFilter === "all" ? LAUNCH : LAUNCH.filter((l) => l.group === launchFilter);
  const navigate = useNavigate();
  const nav = (to: string) => to.startsWith("#") ? document.getElementById(to.slice(1))?.scrollIntoView({ behavior: "smooth" }) : navigate(to);
  const toast = useToast();
  const isAdmin = getUser().role === "admin";

  const rows: any[] = data?.assessments || [];
  const stats = useMemo(() => {
    const scored = rows.filter((r) => r.overall.comparable != null);
    const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
    return {
      n: rows.length,
      industries: new Set(rows.map((r) => r.industry?.key)).size,
      avg: avg(scored.map((r) => r.overall.comparable)),
      gaps: rows.reduce((a, r) => a + r.critical_gaps, 0),
      high: rows.reduce((a, r) => a + r.risks.high, 0),
      verify: avg(rows.filter((r) => r.human_verification != null).map((r) => r.human_verification)),
    };
  }, [rows]);
  const usedBy = useMemo(() => {
    const m: Record<string, any[]> = {};
    rows.forEach((r) => r.industry && (m[r.industry.key] = [...(m[r.industry.key] || []), r]));
    return m;
  }, [rows]);
  const compliance = useMemo(() => {
    const keys = ["potentially_applicable", "unknown", "confirmed_applicable", "verified", "not_applicable"];
    const tot: Record<string, number> = Object.fromEntries(keys.map((k) => [k, 0]));
    rows.forEach((r) => keys.forEach((k) => (tot[k] += r.compliance[k] || 0)));
    return keys.map((k) => ({ k, n: tot[k] }));
  }, [rows]);

  if (!data) return <ErrorBox error={error} />;
  const p = data.platform;
  const packsTotal = Object.values(p.packs_by_kind as Record<string, number>).reduce((a, b) => a + b, 0);
  const selInd = p.industries.find((i: any) => i.key === ind);

  const seed = async () => {
    setBusy(true);
    try { const r = await api.post("/api/demo/seed"); toast(`Demo portfolio loaded: ${r.created.length} assessments`); reload(); }
    catch (e) { toast(errorText(e), "err"); } finally { setBusy(false); }
  };
  const clear = async () => { try { await api.del("/api/demo/seed"); toast("Demo data removed", "info"); reload(); } catch (e) { toast(errorText(e), "err"); } };
  const showTip = (e: React.MouseEvent, body: ReactNode) => setTip({ x: e.clientX + 14, y: e.clientY + 14, body });

  const ranked = [...rows].sort((a, b) => (b.overall[rankBy] ?? -1) - (a.overall[rankBy] ?? -1));
  const maxComp = Math.max(1, ...compliance.map((c) => c.n));

  return (
    <div onMouseLeave={() => setTip(null)}>
      <div className="page-head">
        <div className="ph-l">
          <span className="ph-ico" aria-hidden>◆</span>
          <div><h1>Executive Showcase</h1><p>Domain-specific project assessments &amp; portfolio readiness on {brand.company} {brand.product}</p></div>
        </div>
        <div className="row">
          {isAdmin && rows.some((r) => r.demo) && <button className="btn-outline" onClick={clear}>Remove demo data</button>}
          {isAdmin && <button className="btn-outline" disabled={busy} onClick={seed}>{busy ? "Loading demo…" : rows.some((r) => r.demo) ? "↻ Reset demo portfolio" : "＋ Load demo portfolio"}</button>}
          <button className="btn-outline" onClick={reload}>⟳ Refresh All</button>
        </div>
      </div>

      <div className="kpis">
        <Kpi tone="k-magenta" icon="▤" label="Assessments" v={<CountUp value={stats.n} />} sub="Active client projects" />
        <Kpi tone="k-purple" icon="◆" label="Industries" v={<>{<CountUp value={stats.industries} />}<span style={{ fontSize: 16, opacity: .8 }}> / {p.packs_by_kind.industry || 0}</span></>} sub={`${packsTotal} domain packs live`} />
        <Kpi tone="k-green" icon="✓" label="Avg readiness" v={<CountUp value={stats.avg} suffix="%" />} sub="Comparable score across projects" />
        <Kpi tone="k-red" icon="✕" label="Critical gaps" v={<CountUp value={stats.gaps} />} sub="Needs attention" />
        <Kpi tone="k-orange" icon="✓" label="Human verified" v={<CountUp value={stats.verify} suffix="%" />} sub="Answers & reviews checked" />
      </div>

      <div className="chiprow">
        {LAUNCH_GROUPS.map((g) => (
          <button key={g.key} className={`fchip ${launchFilter === g.key ? "on" : ""}`} onClick={() => setLaunchFilter(g.key)}>
            {g.label} <span className="n">{g.key === "all" ? LAUNCH.length : LAUNCH.filter((l) => l.group === g.key).length}</span>
          </button>))}
      </div>
      <div className="sec-rule">{(LAUNCH_GROUPS.find((g) => g.key === launchFilter)?.label || "").toUpperCase()} <span className="n">{launchCards.length}</span></div>
      <div className="launch">
        {launchCards.map((l) => (
          <div key={l.title} className={`lcard ${l.tone}`} onClick={() => nav(l.to)} role="link" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && nav(l.to)}>
            <div className="li" aria-hidden>{l.icon}</div>
            <div className="lt">{l.title}</div>
            <div className="ld">{l.desc}</div>
            <div className="lc">{l.cta} →</div>
          </div>))}
      </div>
      <div className="sec-rule">PORTFOLIO <span className="n">{rows.length}</span></div>

      {rows.length === 0 ? (
        <Card title="No assessed projects yet">
          <p>Create an assessment, or {isAdmin ? <button className="link" onClick={seed}>load the demo portfolio</button> : "ask an admin to load the demo portfolio"} (5 synthetic clients across banking, healthcare, retail, manufacturing and telecom) to see this view populated.</p>
        </Card>
      ) : (
        <>
          <div id="heatmap" /><Card title="Readiness heatmap – projects × readiness areas" actions={<span className="small muted">Hover a cell for detail · click a project to open it</span>}>
            <div style={{ overflowX: "auto" }}>
              <table className="heat">
                <thead><tr><th className="rowh">Client · project</th>{GROUPS.map(([, l]) => <th key={l}>{l}</th>)}<th>Overall</th></tr></thead>
                <tbody>{rows.map((r) => (
                  <tr key={r.id} className="rowlink">
                    <td className="rowh" onClick={() => nav(`/assessments/${r.id}`)}><strong>{r.client_name}</strong><div className="small muted">{r.project_name} · {r.industry?.name}</div></td>
                    {GROUPS.map(([g, l]) => {
                      const s = r.groups[g]?.score ?? null, st = ragState(s);
                      return (
                        <td key={g} className={`cell cell-${st.state}`} onClick={() => nav(`/assessments/${r.id}`)}
                            onMouseMove={(e) => showTip(e, <><b>{r.client_name}</b> · {l}<br />{s == null ? "Not assessed (no scored answers yet)" : `${s.toFixed(0)}% – ${st.label}`}</>)}
                            onMouseLeave={() => setTip(null)}>
                          {s == null ? "–" : s.toFixed(0)}<small>{st.icon} {st.label.split(" – ")[0]}</small>
                        </td>);
                    })}
                    {(() => { const s = r.overall.comparable, st = ragState(s); return (
                      <td className={`cell cell-${st.state}`} onClick={() => nav(`/assessments/${r.id}`)}
                          onMouseMove={(e) => showTip(e, <><b>{r.client_name}</b> overall<br />Comparable {s?.toFixed(0) ?? "–"}% · domain-adjusted {r.overall.domain_adjusted?.toFixed(0) ?? "–"}%<br />{r.answered}/{r.questions} questions answered</>)}
                          onMouseLeave={() => setTip(null)}>{s == null ? "–" : s.toFixed(0)}<small>{st.icon} {st.label.split(" – ")[0]}</small></td>); })()}
                  </tr>))}</tbody>
              </table>
            </div>
            <div className="legend"><span><i style={{ background: "#d6f2d6" }} />● Green ≥ {data.reference.rag_thresholds.green}%</span><span><i style={{ background: "#fff0c7" }} />▲ Amber ≥ {data.reference.rag_thresholds.amber}%</span><span><i style={{ background: "#fbd9d6" }} />■ Red below</span><span><i style={{ background: "#efedf4" }} />○ Not assessed</span></div>
          </Card>

          <div className="grid-2">
            <Card title="Readiness ranking" actions={
              <div className="seg"><button className={rankBy === "comparable" ? "on" : ""} onClick={() => setRankBy("comparable")}>Comparable</button>
                <button className={rankBy === "domain_adjusted" ? "on" : ""} onClick={() => setRankBy("domain_adjusted")}>Domain-adjusted</button></div>}>
              {ranked.map((r) => <Meter key={r.id} label={r.client_name} sub={`${r.industry?.name} · ${r.stage}`} value={r.overall[rankBy]} onClick={() => nav(`/assessments/${r.id}`)} />)}
              <p className="small muted">Comparable = global dimensions only, so projects in different industries can be ranked fairly. Domain-adjusted adds industry and technology dimensions.</p>
            </Card>
            <Card title="Risk exposure & open work">
              <table>
                <thead><tr><th>Project</th><th style={{ width: "38%" }}>Risks (high vs other)</th><th>Critical gaps</th><th>Conflicts</th><th>Evidence</th></tr></thead>
                <tbody>{rows.map((r) => (
                  <tr key={r.id} onMouseMove={(e) => showTip(e, <><b>{r.client_name}</b><br />{r.risks.total} risks · {r.risks.high} high · {r.risks.evidenced} evidenced in client documents</>)} onMouseLeave={() => setTip(null)}>
                    <td><Link to={`/assessments/${r.id}/risks`}>{r.client_name}</Link></td>
                    <td><div className="seg-bar" aria-label={`${r.risks.high} high of ${r.risks.total}`}>
                      <div style={{ width: `${(100 * r.risks.high) / Math.max(1, r.risks.total)}%`, background: "var(--crit)" }} />
                      <div style={{ flex: 1, background: "#d9d6e3" }} /></div>
                      <span className="small">{r.risks.high} high / {r.risks.total}</span></td>
                    <td><strong style={{ color: r.critical_gaps ? "var(--red)" : "var(--green)" }}>{r.critical_gaps}</strong></td>
                    <td>{r.conflicts_pending}</td>
                    <td>{r.evidence_coverage == null ? "–" : `${r.evidence_coverage.toFixed(0)}%`}</td>
                  </tr>))}</tbody>
              </table>
              <div className="legend"><span><i style={{ background: "var(--crit)" }} />High-rated risks</span><span><i style={{ background: "#d9d6e3" }} />Medium / low</span></div>
            </Card>
          </div>

          <div className="grid-2">
            <div id="compliance" /><Card title="Compliance pipeline (all projects)">
              {compliance.map((c) => (
                <div key={c.k} className="meter" onMouseMove={(e) => showTip(e, <>{c.n} regulatory items · {c.k.replace(/_/g, " ")}</>)} onMouseLeave={() => setTip(null)}>
                  <div className="meter-label">{c.k.replace(/_/g, " ")}</div>
                  <div className="meter-track"><div className="meter-fill" style={{ width: `${(100 * c.n) / maxComp}%`, background: "var(--seq-4)" }} /></div>
                  <div className="meter-fig">{c.n}</div><div className="meter-status small muted">{c.k === "potentially_applicable" ? "awaiting review" : c.k === "verified" ? "evidence on file" : ""}</div>
                </div>))}
              <p className="small muted">The platform only ever suggests "potentially applicable". Confirmation and verification are recorded by authorised reviewers.</p>
            </Card>
            <Card title="Questions by origin (portfolio)">
              {(() => {
                const o: Record<string, number> = {};
                rows.forEach((r) => Object.entries(r.questions_by_origin as Record<string, number>).forEach(([k, v]) => (o[k] = (o[k] || 0) + v)));
                const max = Math.max(1, ...Object.values(o));
                return Object.entries(o).map(([k, v]) => (
                  <div key={k} className="meter"><div className="meter-label">{k}</div>
                    <div className="meter-track"><div className="meter-fill" style={{ width: `${(100 * v) / max}%`, background: "var(--seq-5)" }} /></div>
                    <div className="meter-fig">{v}</div><div /></div>));
              })()}
              <p className="small muted">Most questions come from industry, sub-domain and technology packs – proof the assessment adapts to each client.</p>
            </Card>
          </div>
        </>
      )}

      <div id="industries" /><Card title={`Industry coverage – ${p.industries.length} domain packs`} actions={<span className="small muted">Click an industry to see what its pack contains</span>}>
        <div className="ind-grid">
          {p.industries.map((i: any) => (
            <div key={i.key} className={`ind-tile ${usedBy[i.key] ? "used" : ""} ${ind === i.key ? "sel" : ""}`} onClick={() => setInd(ind === i.key ? null : i.key)}>
              <div className="n">{i.name}</div>
              <div className="m">{i.sub_domains.length} sub-domains · {i.questions} questions</div>
              {usedBy[i.key] && <div className="m" style={{ color: "var(--brand)" }}>● {usedBy[i.key].length} active assessment{usedBy[i.key].length > 1 ? "s" : ""}</div>}
            </div>))}
        </div>
        {selInd && (
          <div className="card drawer" style={{ marginTop: 14 }}>
            <div className="card-h"><h3>{selInd.name} <span className="muted small">pack v{selInd.version}</span></h3><button className="link" onClick={() => setInd(null)}>Close</button></div>
            <div className="grid-3">
              <div className="kpi-tile"><div className="v">{selInd.questions}</div><div className="l">industry questions</div></div>
              <div className="kpi-tile"><div className="v">{selInd.risks}</div><div className="l">risks in catalog</div></div>
              <div className="kpi-tile"><div className="v">{selInd.compliance}</div><div className="l">regulatory references</div></div>
            </div>
            <h4>Sub-domains</h4><div className="chips">{selInd.sub_domains.map((s: string) => <span key={s} className="chip">{s}</span>)}</div>
            <h4>Extra scoring dimensions</h4><div className="chips">{selInd.dimensions.map((s: string) => <span key={s} className="chip">{s}</span>)}</div>
            <p className="small muted">{selInd.kpis} KPIs and {selInd.terms} terminology entries also ship with this pack.</p>
            {usedBy[selInd.key] && <p>Active: {usedBy[selInd.key].map((r) => <Link key={r.id} to={`/assessments/${r.id}`} style={{ marginRight: 10 }}>{r.client_name}</Link>)}</p>}
          </div>
        )}
      </Card>

      <Card title="Why this matters">
        <div className="cap-grid">{CAPABILITIES.map((c) => <div key={c.t} className="cap"><div className="t"><span>{c.i}</span>{c.t}</div><p>{c.d}</p></div>)}</div>
        <p className="small muted" style={{ marginTop: 12 }}>Platform content: {p.totals.questions} questions · {p.totals.risks} risks · {p.totals.kpis} KPIs · {p.totals.compliance} regulatory references · {p.totals.terminology} domain terms · {p.totals.architecture_patterns} architecture patterns.</p>
      </Card>

      {tip && <div className="tip" style={{ left: tip.x, top: tip.y }}>{tip.body}</div>}
    </div>
  );
}

function Kpi({ tone, icon, label, v, sub }: { tone: string; icon: string; label: string; v: ReactNode; sub: string }) {
  return (
    <div className={`kpi ${tone}`}>
      <span className="k-i" aria-hidden>{icon}</span>
      <div className="k-l">{label}</div><div className="k-v">{v}</div><div className="k-s">{sub}</div>
    </div>
  );
}
