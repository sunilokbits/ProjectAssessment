import { useMemo, useState } from "react";
import { Link, NavLink, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, errorText, getUser } from "../api";
import { Card, CountUp, ErrorBox, Meter, Origin, Pill, Source, pct, ragState, useApi, useToast } from "../components";

const ORIGINS = ["GLOBAL", "INDUSTRY", "SUB-DOMAIN", "TECHNOLOGY", "PROJECT", "AI-DISCOVERED"];

export default function AssessmentView() {
  const { id } = useParams();
  const a = useApi<any>(`/api/assessments/${id}`);
  if (!a.data) return <ErrorBox error={a.error} />;
  const base = `/assessments/${id}`;
  const tabs = [["", "Dashboard"], ["questionnaire", "Questionnaire"], ["risks", "Risks"], ["kpis", "KPIs"],
    ["compliance", "Compliance"], ["architecture", "Architecture"], ["recommendations", "Recommendations"],
    ["requirements", "Requirements"], ["knowledge", "NFRs & assumptions"], ["provenance", "Domain packs & provenance"],
    ["ai", "AI context"]];
  return (
    <div>
      <WorkspaceHeader id={id!} a={a.data} base={base} />
      <nav className="tabs">
        {tabs.map(([p, l]) => <NavLink key={p} to={p ? `${base}/${p}` : base} end>{l}</NavLink>)}
      </nav>
      <Routes>
        <Route index element={<Dashboard id={id!} />} />
        <Route path="questionnaire" element={<Questionnaire id={id!} />} />
        <Route path="risks" element={<Risks id={id!} />} />
        <Route path="kpis" element={<Kpis id={id!} />} />
        <Route path="compliance" element={<Compliance id={id!} />} />
        <Route path="architecture" element={<Architecture id={id!} />} />
        <Route path="recommendations" element={<Recommendations id={id!} />} />
        <Route path="requirements" element={<Requirements id={id!} />} />
        <Route path="knowledge" element={<Knowledge id={id!} />} />
        <Route path="provenance" element={<Provenance id={id!} assessment={a.data} reload={a.reload} />} />
        <Route path="ai" element={<AiContext id={id!} />} />
      </Routes>
    </div>
  );
}

// ------------------------------------------------------------------ header
function WorkspaceHeader({ id, a, base }: { id: string; a: any; base: string }) {
  const d = useApi<any>(`/api/assessments/${id}/dashboard`).data;
  const prim = a.mappings.find((m: any) => m.role === "primary");
  const tech = a.mappings.filter((m: any) => m.role === "technology");
  const s = d?.scores.overall.comparable ?? null, st = ragState(s);
  return (
    <div className="ws-head">
      <div>
        <div className="eyebrow">{a.client_name} · {a.stage}</div>
        <h2>{a.project_name}</h2>
        <div className="chips" style={{ marginTop: 8 }}>
          {prim && <span className="chip">{prim.pack_name}</span>}
          {prim?.sub_domains.map((x: string) => <span key={x} className="chip">{x.replace(/_/g, " ")}</span>)}
          {tech.map((m: any) => <span key={m.pack_key} className="chip">{m.pack_name}</span>)}
        </div>
      </div>
      <div className="row" style={{ gap: 18 }}>
        <div className="ws-score"><div className="v"><CountUp value={s} suffix="%" /></div><div className="l">{st.icon} {st.label} · comparable readiness</div></div>
        <Link to={`${base}/classify`} className="button" style={{ background: "rgba(255,255,255,.12)", color: "#fff", borderColor: "rgba(255,255,255,.3)" }}>Change classification</Link>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ dashboard
function TreeNode({ label, items }: { label: string; items: string[] }) {
  return (
    <li><span className="tree-label">{label}</span>
      <ul>{items.length ? items.map((x) => <li key={x}>{x}</li>) : <li className="muted">not specified</li>}</ul>
    </li>
  );
}

function OverallRow({ label, v }: { label: string; v: number | null }) {
  const st = ragState(v);
  return (
    <div className="meter overall"><div className="meter-label">{label}</div>
      <div className="meter-track"><div className={`meter-fill rag-bg-${st.state}`} style={{ width: `${v ?? 0}%` }} /></div>
      <div className="meter-fig">{pct(v)}</div><div className={`meter-status st-${st.state}`}>{st.icon} {st.label.split(" – ")[0]}</div></div>
  );
}

function Dashboard({ id }: { id: string }) {
  const { data, error } = useApi<any>(`/api/assessments/${id}/dashboard`);
  const qn = useApi<any>(`/api/assessments/${id}/questionnaire`).data;
  const risks = useApi<any[]>(`/api/assessments/${id}/risks`).data;
  const [group, setGroup] = useState<string | null>(null);
  const [showMethod, setShowMethod] = useState(false);
  const nav = useNavigate();
  if (!data) return <ErrorBox error={error} />;
  const c = data.classification, s = data.summary, sc = data.scores;
  const g = sc.groups.find((x: any) => x.group === group);
  const dims = g ? sc.dimensions.filter((d: any) => d.group === g.group) : [];
  const originProgress = ORIGINS.map((o) => {
    const qs = (qn?.questions || []).filter((q: any) => q.origin === o);
    return { o, total: qs.length, done: qs.filter((q: any) => q.answer && q.answer.value != null && q.answer.value !== "").length };
  }).filter((x) => x.total);
  const nba = [
    ...s.critical_gaps.slice(0, 4).map((gp: any) => ({ t: `Answer critical question: ${gp.text}`, to: `questionnaire?dim=${gp.dimension}`, tone: "red" })),
    s.conflicts_pending ? { t: `Resolve ${s.conflicts_pending} conflicting recommendation(s)`, to: "recommendations", tone: "amber" } : null,
    s.compliance.potentially_applicable ? { t: `Review ${s.compliance.potentially_applicable} suggested regulation(s) with legal/compliance`, to: "compliance", tone: "amber" } : null,
    s.risks.high ? { t: `Agree mitigations for ${s.risks.high} high-rated risk(s)`, to: "risks", tone: "amber" } : null,
  ].filter(Boolean) as { t: string; to: string; tone: string }[];
  return (
    <div className="grid-dash">
      <div>
        <Card title="Domain coverage">
          <ul className="tree">
            <li><span className="tree-label">CLIENT</span> <strong>{c.client}</strong>
              <ul>
                <TreeNode label="Industry" items={c.industry.map((x: any) => x.name)} />
                <TreeNode label="Sub-domain" items={c.sub_domains.map((x: any) => x.name)} />
                {c.secondary_industries.length > 0 && <TreeNode label="Secondary domains" items={c.secondary_industries.map((x: any) => x.name)} />}
                <TreeNode label="Project Type" items={c.project_types.map((x: any) => x.name)} />
                <TreeNode label="Technology" items={c.technologies.map((x: any) => x.name)} />
                <TreeNode label="Geography" items={c.geography ? [c.geography.name] : []} />
                {c.data_classifications.length > 0 && <TreeNode label="Data classification" items={c.data_classifications} />}
              </ul>
            </li>
          </ul>
          <p className="muted small">Classification confirmed by {c.confirmed_by || "—"}.</p>
        </Card>
        <Card title="Risk matrix" actions={<span className="small muted">click a cell</span>}>
          <RiskMatrix risks={risks || []} onPick={(l, i) => nav(`risks?l=${l}&i=${i}`)} />
        </Card>
        <Card title="Questionnaire progress by origin">
          {originProgress.map((x) => (
            <div key={x.o} className="meter clickable" onClick={() => nav(`questionnaire?origin=${encodeURIComponent(x.o)}`)}>
              <div className="meter-label"><Origin origin={x.o} /></div>
              <div className="meter-track"><div className="meter-fill" style={{ width: `${(100 * x.done) / x.total}%`, background: "var(--seq-4)" }} /></div>
              <div className="meter-fig">{x.done}/{x.total}</div><div />
            </div>))}
        </Card>
      </div>

      <div>
        <Card title="Readiness – click an area to drill down" actions={<button className="link" onClick={() => setShowMethod(!showMethod)}>{showMethod ? "Hide" : "Show"} scoring weights</button>}>
          {sc.groups.map((gr: any) => <Meter key={gr.group} label={gr.label} value={gr.score} active={group === gr.group}
            sub={showMethod ? `group weight ${gr.weight} · ${gr.dimensions.length} dimensions` : undefined}
            onClick={() => setGroup(group === gr.group ? null : gr.group)} />)}
          <OverallRow label="Overall (comparable)" v={sc.overall.comparable} />
          <OverallRow label="Overall (domain-adjusted)" v={sc.overall.domain_adjusted} />
          {g && (
            <div className="card drawer page-enter" style={{ marginTop: 12 }}>
              <div className="card-h"><h3>{g.label}: dimensions</h3><button className="link" onClick={() => setGroup(null)}>Close</button></div>
              {dims.map((d: any) => (
                <Meter key={d.key} label={<>{d.name} {d.comparable && <Pill>comparable</Pill>}</>} value={d.score}
                  sub={`weight ${d.weight} · ${d.answered}/${d.questions} answered · ${d.source?.pack_name || ""}`}
                  onClick={() => nav(`questionnaire?dim=${d.key}`)} />))}
              <p className="small muted">Click a dimension to open its questions.</p>
            </div>
          )}
          {showMethod && (
            <ul className="small method">{Object.entries(sc.method).map(([k, v]) => <li key={k}><strong>{k}</strong>: {typeof v === "string" ? v : JSON.stringify(v)}</li>)}</ul>
          )}
        </Card>

        <Card title="Next best actions">
          <ol className="nba">{nba.map((a, k) => <li key={k}><Link to={a.to}>{a.t}</Link> <Pill tone={a.tone}>{a.tone === "red" ? "critical" : "review"}</Pill></li>)}
            {nba.length === 0 && <li className="muted">Nothing urgent – keep collecting evidence and verifying answers.</li>}</ol>
        </Card>

        <Card title="Status">
          <div className="stats">
            <Stat label="Critical gaps" value={s.critical_gaps.length} tone={s.critical_gaps.length ? "red" : "green"} />
            <Stat label="Open questions" value={`${s.open_questions}/${s.questions_total}`} />
            <Stat label="Risks (high)" value={`${s.risks.total} (${s.risks.high})`} tone={s.risks.high ? "amber" : ""} />
            <Stat label="Assumptions" value={s.assumptions} />
            <Stat label="Dependencies" value={s.dependencies} />
            <Stat label="Compliance items" value={Object.values(s.compliance as Record<string, number>).reduce((a, b) => a + b, 0)} />
            <Stat label="Conflicts to review" value={s.conflicts_pending} tone={s.conflicts_pending ? "amber" : ""} />
            <Stat label="Evidence coverage" value={pct(s.evidence_coverage.answered_with_evidence)} />
            <Stat label="AI confidence (classification)" value={s.ai_confidence.classification != null ? `${Math.round(s.ai_confidence.classification * 100)}%` : "–"} />
            <Stat label="Human verification" value={pct(s.human_verification.progress)} />
          </div>
          <p className="small muted">{s.duplicates_removed} duplicate / equivalent questions merged across packs · {s.requirements_extracted} requirements extracted from documents.</p>
        </Card>
      </div>
    </div>
  );
}

function RiskMatrix({ risks, onPick }: { risks: any[]; onPick: (l: number, i: number) => void }) {
  const [tip, setTip] = useState<{ x: number; y: number; t: string } | null>(null);
  const count = (l: number, i: number) => risks.filter((r) => r.likelihood === l && r.impact === i);
  const max = Math.max(1, ...[1, 2, 3, 4, 5].flatMap((l) => [1, 2, 3, 4, 5].map((i) => count(l, i).length)));
  return (
    <div onMouseLeave={() => setTip(null)}>
      <div className="matrix">
        {[5, 4, 3, 2, 1].map((l) => (
          <div key={l} style={{ display: "contents" }}>
            <div className="ax">{l}</div>
            {[1, 2, 3, 4, 5].map((i) => {
              const rs = count(l, i), n = rs.length, step = n ? Math.max(1, Math.ceil((6 * n) / max)) : 0;
              return <div key={i} className={`mcell seq-${step}`} onClick={() => n && onPick(l, i)}
                onMouseMove={(e) => setTip({ x: e.clientX + 12, y: e.clientY + 12, t: n ? `L${l} × I${i}: ${rs.map((r) => r.title).slice(0, 4).join("; ")}${n > 4 ? "…" : ""}` : `L${l} × I${i}: no risks` })}>{n || ""}</div>;
            })}
          </div>))}
        <div />{[1, 2, 3, 4, 5].map((i) => <div key={i} className="ax">{i}</div>)}
      </div>
      <div className="small muted" style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}><span>↑ likelihood</span><span>impact →</span></div>
      <div className="legend"><span><i style={{ background: "var(--seq-1)" }} />fewer</span><span><i style={{ background: "var(--seq-6)" }} />more risks in cell</span></div>
      {tip && <div className="tip" style={{ left: tip.x, top: tip.y }}>{tip.t}</div>}
    </div>
  );
}

function Stat({ label, value, tone = "" }: { label: string; value: any; tone?: string }) {
  return <div className={`stat ${tone}`}><div className="stat-v">{value}</div><div className="stat-l">{label}</div></div>;
}

// ------------------------------------------------------------------ questionnaire
function AnswerInput({ q, value, onChange }: { q: any; value: any; onChange: (v: any) => void }) {
  if (q.answer_type === "yes_no")
    return (
      <div className="seg">
        {(q.options.length ? q.options : [{ value: "yes", label: "Yes" }, { value: "partial", label: "Partial" }, { value: "no", label: "No" }, { value: "unknown", label: "Unknown" }])
          .map((o: any) => <button key={o.value} className={value === o.value ? "on" : ""} onClick={() => onChange(o.value)}>{o.label}</button>)}
      </div>
    );
  if (q.answer_type === "scale")
    return <div className="seg">{[1, 2, 3, 4, 5].map((n) => <button key={n} className={Number(value) === n ? "on" : ""} onClick={() => onChange(n)}>{n}</button>)}</div>;
  if (q.answer_type === "single_choice")
    return (
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">— select —</option>
        {q.options.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  if (q.answer_type === "multi_choice") {
    const v: string[] = Array.isArray(value) ? value : [];
    return <div>{q.options.map((o: any) => <label key={o.value} className="check"><input type="checkbox" checked={v.includes(o.value)} onChange={(e) => onChange(e.target.checked ? [...v, o.value] : v.filter((x) => x !== o.value))} />{o.label}</label>)}</div>;
  }
  return <textarea rows={2} defaultValue={value ?? ""} onBlur={(e) => onChange(e.target.value)} />;
}

function Questionnaire({ id }: { id: string }) {
  const { data, error, reload } = useApi<any>(`/api/assessments/${id}/questionnaire`);
  const [params, setParams] = useSearchParams();
  const filter = params.get("origin") || "ALL";
  const dim = params.get("dim");
  const setFilter = (o: string) => { const n = new URLSearchParams(params); o === "ALL" ? n.delete("origin") : n.set("origin", o); setParams(n); };
  const [onlyOpen, setOnlyOpen] = useState(false);
  const toast = useToast();
  const [err, setErr] = useState<string | null>(null);
  const canReview = ["admin", "reviewer"].includes(getUser().role);
  const qs = useMemo(() => (data?.questions || []).filter((q: any) =>
    (filter === "ALL" || q.origin === filter) && (!dim || q.dimension === dim) && (!onlyOpen || !q.answer)), [data, filter, dim, onlyOpen]);
  if (!data) return <ErrorBox error={error} />;

  const save = async (q: any, patch: any) => {
    try {
      await api.put(`/api/assessments/${id}/answers/${encodeURIComponent(q.key)}`, { value: q.answer?.value ?? null, evidence: q.answer?.evidence ?? "", notes: q.answer?.notes ?? "", ...patch });
      toast("Answer saved");
      reload();
    } catch (e) { setErr(errorText(e)); }
  };
  const verify = async (q: any) => { try { await api.post(`/api/assessments/${id}/answers/${encodeURIComponent(q.key)}/verify`); reload(); } catch (e) { setErr(errorText(e)); } };
  const reviewAi = async (q: any, status: string) => { await api.patch(`/api/assessments/${id}/ai-questions/${q.id}`, { status }); reload(); };

  return (
    <Card title={`Questionnaire (${qs.length} of ${data.questions.length})`} actions={
      <div className="row">
        <select value={filter} onChange={(e) => setFilter(e.target.value)}><option value="ALL">All origins</option>{ORIGINS.map((o) => <option key={o}>{o}</option>)}</select>
        <label className="check"><input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} />Open only</label>
      </div>}>
      {(() => { const all = data.questions, done = all.filter((q: any) => q.answer && q.answer.value != null && q.answer.value !== "").length; return (
        <div className="meter" style={{ marginBottom: 8 }}><div className="meter-label"><strong>Overall progress</strong></div>
          <div className="meter-track"><div className="meter-fill" style={{ width: `${(100 * done) / all.length}%`, background: "var(--brand-2)" }} /></div>
          <div className="meter-fig">{done}/{all.length}</div><div className="small muted">answered</div></div>); })()}
      {dim && <div className="notice">Showing questions for dimension <strong>{dim}</strong> · <button className="link" onClick={() => { const n = new URLSearchParams(params); n.delete("dim"); setParams(n); }}>show all</button></div>}
      <ErrorBox error={err} />
      {qs.map((q: any) => (
        <div key={q.key} className={`q ${q.critical ? "critical" : ""}`}>
          <div className="q-head">
            <Origin origin={q.origin} />
            {q.critical && <Pill tone="red">critical</Pill>}
            {q.evidence_required && <Pill>evidence required</Pill>}
            <span className="muted small">{q.dimension} · weight {q.weight}</span>
            <Source s={q.source} />
          </div>
          <div className="q-text">{q.text}</div>
          {q.help && <div className="muted small">{q.help}</div>}
          {q.applies_because?.length > 0 && <div className="small why">Applies because: {q.applies_because.join("; ")}</div>}
          {q.merged_from?.length > 0 && <details className="small"><summary>{q.merged_from.length} equivalent question(s) merged</summary>
            <ul>{q.merged_from.map((m: any) => <li key={m.key}><Origin origin={m.origin} /> {m.text} <span className="muted">({m.pack_key}; {m.reason})</span></li>)}</ul></details>}
          {q.origin === "AI-DISCOVERED" && (
            <div className="small">Confidence {q.confidence != null ? Math.round(q.confidence * 100) + "%" : "–"} · status {q.status}
              {" "}<button className="link" onClick={() => reviewAi(q, "accepted")}>accept</button> · <button className="link" onClick={() => reviewAi(q, "dismissed")}>dismiss</button></div>)}
          <div className="q-answer">
            <AnswerInput q={q} value={q.answer?.value} onChange={(v) => save(q, { value: v })} />
            <input className="evidence" placeholder="Evidence (document, section, link)" defaultValue={q.answer?.evidence || ""}
                   onBlur={(e) => e.target.value !== (q.answer?.evidence || "") && save(q, { evidence: e.target.value })} />
            {q.answer && (q.answer.verified
              ? <Pill tone="green">verified by {q.answer.verified_by}</Pill>
              : canReview ? <button onClick={() => verify(q)}>Verify</button> : <Pill tone="amber">unverified</Pill>)}
          </div>
        </div>
      ))}
    </Card>
  );
}

// ------------------------------------------------------------------ risks
function Risks({ id }: { id: string }) {
  const { data: all, error, reload } = useApi<any[]>(`/api/assessments/${id}/risks`);
  const [params, setParams] = useSearchParams();
  const fl = params.get("l"), fi = params.get("i");
  const data = all && (fl ? all.filter((r) => String(r.likelihood) === fl && String(r.impact) === fi) : all);
  const [f, setF] = useState({ title: "", likelihood: 3, impact: 3, mitigation: "" });
  if (!data) return <ErrorBox error={error} />;
  const add = async () => { await api.post(`/api/assessments/${id}/risks`, f); setF({ title: "", likelihood: 3, impact: 3, mitigation: "" }); reload(); };
  return (
    <Card title={`Risk register (${data.length}) — global + industry + technology + project`}>
      {fl && <div className="notice">Filtered to likelihood {fl} × impact {fi} · <button className="link" onClick={() => setParams(new URLSearchParams())}>show all</button></div>}
      <table>
        <thead><tr><th>Origin</th><th>Risk</th><th>L×I</th><th>Rating</th><th>Mitigation</th><th>Evidence in documents</th></tr></thead>
        <tbody>{data.map((r) => (
          <tr key={r.key}><td><Origin origin={r.origin} /><br /><Source s={r.source} /></td><td><strong>{r.title}</strong><div className="small muted">{r.description}</div></td>
            <td>{r.likelihood}×{r.impact}={r.score}</td><td><Pill tone={r.rating === "high" ? "red" : r.rating === "medium" ? "amber" : "green"}>{r.rating}</Pill></td>
            <td className="small">{r.mitigation}</td><td className="small">{r.evidence.join(", ") || "–"}</td></tr>))}
        </tbody>
      </table>
      <h4>Add project-specific risk</h4>
      <div className="row">
        <input placeholder="Risk title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
        <label>L <input type="number" min={1} max={5} value={f.likelihood} onChange={(e) => setF({ ...f, likelihood: +e.target.value })} /></label>
        <label>I <input type="number" min={1} max={5} value={f.impact} onChange={(e) => setF({ ...f, impact: +e.target.value })} /></label>
        <input placeholder="Mitigation" value={f.mitigation} onChange={(e) => setF({ ...f, mitigation: e.target.value })} />
        <button disabled={!f.title} onClick={add}>Add</button>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ KPIs
function Kpis({ id }: { id: string }) {
  const { data, error, reload } = useApi<any[]>(`/api/assessments/${id}/kpis`);
  const [err, setErr] = useState<string | null>(null);
  if (!data) return <ErrorBox error={error} />;
  const review = async (k: any, status: string, target?: string, source?: string) => {
    try { await api.put(`/api/assessments/${id}/kpis/${encodeURIComponent(k.key)}`, { status, client_target: target || null, target_source: source || null }); reload(); setErr(null); }
    catch (e) { setErr(errorText(e)); }
  };
  return (
    <Card title="Recommended KPIs — confirm the relevant ones">
      <p className="muted small">KPI catalogs come from the domain packs. Targets are never generated: a target can only be recorded with its client source.</p>
      <ErrorBox error={err} />
      <table>
        <thead><tr><th>Origin</th><th>KPI</th><th>Direction</th><th>Status</th><th>Client target (with source)</th><th /></tr></thead>
        <tbody>{data.map((k) => (
          <tr key={k.key}><td><Origin origin={k.origin} /></td><td><strong>{k.name}</strong><div className="small muted">{k.description}{k.formula && ` · ${k.formula}`}</div></td>
            <td className="small">{k.direction.replace(/_/g, " ")}{k.unit && ` (${k.unit})`}</td>
            <td><Pill tone={k.status === "confirmed" ? "green" : k.status === "rejected" ? "red" : ""}>{k.status}</Pill></td>
            <td className="small">{k.client_target ? `${k.client_target} — source: ${k.target_source}` : <KpiTarget onSave={(t, s) => review(k, "confirmed", t, s)} />}</td>
            <td><button onClick={() => review(k, "confirmed")}>Confirm</button> <button onClick={() => review(k, "rejected")}>Not relevant</button></td></tr>))}
        </tbody>
      </table>
    </Card>
  );
}
function KpiTarget({ onSave }: { onSave: (t: string, s: string) => void }) {
  const [t, setT] = useState(""), [s, setS] = useState("");
  return <span className="row"><input placeholder="target" value={t} onChange={(e) => setT(e.target.value)} style={{ width: 80 }} />
    <input placeholder="client source" value={s} onChange={(e) => setS(e.target.value)} style={{ width: 120 }} />
    <button disabled={!t} onClick={() => onSave(t, s)}>Save</button></span>;
}

// ------------------------------------------------------------------ compliance
function Compliance({ id }: { id: string }) {
  const { data, error, reload } = useApi<any>(`/api/assessments/${id}/compliance`);
  const [err, setErr] = useState<string | null>(null);
  if (!data) return <ErrorBox error={error} />;
  const set = async (c: any, status: string) => {
    const evidence = status === "verified" ? window.prompt("Evidence for verification (audit report, control test, sign-off):") || "" : "";
    try { await api.put(`/api/assessments/${id}/compliance/${c.key}`, { status, evidence }); reload(); setErr(null); } catch (e) { setErr(errorText(e)); }
  };
  return (
    <Card title="Regulatory & compliance items">
      <div className="notice">{data.disclaimer}</div>
      <ErrorBox error={err} />
      <table>
        <thead><tr><th>Regulation</th><th>Why suggested</th><th>Status</th><th>Review</th></tr></thead>
        <tbody>{data.items.map((c: any) => (
          <tr key={c.key}><td><strong>{c.short_name}</strong><div className="small muted">{c.name}</div><Origin origin={c.origin} /> <Source s={c.source} /></td>
            <td className="small"><ul>{c.suggestion_reasons.map((r: string) => <li key={r}>{r}</li>)}{c.open_factors.map((r: string) => <li key={r} className="amber-text">open: {r}</li>)}</ul>
              {c.applicability_note && <em>{c.applicability_note}</em>}</td>
            <td><Pill tone={c.status === "verified" ? "green" : c.status === "confirmed_applicable" ? "blue" : c.status === "not_applicable" ? "" : "amber"}>{c.status_label}</Pill>
              {c.reviewer && <div className="small muted">by {c.reviewer}</div>}{c.evidence && <div className="small">evidence: {c.evidence}</div>}</td>
            <td><select value="" onChange={(e) => e.target.value && set(c, e.target.value)}><option value="">change…</option>
              {Object.entries(data.statuses).map(([k, v]) => <option key={k} value={k}>{String(v)}</option>)}</select></td></tr>))}
        </tbody>
      </table>
    </Card>
  );
}

// ------------------------------------------------------------------ architecture
function Architecture({ id }: { id: string }) {
  const { data, error } = useApi<any>(`/api/assessments/${id}/architecture`);
  if (!data) return <ErrorBox error={error} />;
  return (
    <div>
      <div className="notice">{data.note} {data.patterns.length} of {data.patterns_considered} patterns in the selected domain packs apply.</div>
      {data.patterns.map((p: any) => (
        <Card key={p.key} title={<>{p.name} <Origin origin={p.origin} /></>}>
          <p className="small">{p.description}</p>
          <p className="small why">Selected because: {p.selected_because.join("; ")}</p>
          <div className="arch">
            {p.layers.map((l: any, i: number) => (
              <div key={l.layer}>
                <div className="arch-layer"><div className="arch-name">{l.layer}</div>
                  <div className="arch-comps">{l.components.map((c: any) => <span key={c.id} className="comp" title={c.why.join("; ")}>{c.name}</span>)}</div></div>
                {i < p.layers.length - 1 && <div className="arrow">▼</div>}
              </div>
            ))}
          </div>
          {p.excluded_components.length > 0 && <details className="small"><summary>{p.excluded_components.length} components not included</summary>
            <ul>{p.excluded_components.map((c: any) => <li key={c.id}><strong>{c.name}</strong> — {c.excluded_because}</li>)}</ul></details>}
          {p.considerations.length > 0 && <ul className="small">{p.considerations.map((c: string) => <li key={c}>{c}</li>)}</ul>}
        </Card>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ recommendations
function Recommendations({ id }: { id: string }) {
  const { data, error, reload } = useApi<any>(`/api/assessments/${id}/recommendations`);
  const [err, setErr] = useState<string | null>(null);
  if (!data) return <ErrorBox error={error} />;
  const resolve = async (c: any, chosen: string) => {
    const rationale = window.prompt("Rationale for this decision:");
    if (!rationale) return;
    try { await api.put(`/api/assessments/${id}/conflicts/${encodeURIComponent(c.key)}`, { chosen, rationale }); reload(); setErr(null); } catch (e) { setErr(errorText(e)); }
  };
  return (
    <div>
      <ErrorBox error={err} />
      {data.conflicts.length > 0 && (
        <Card title={`Conflicting recommendations — human review (${data.conflicts.length})`}>
          {data.conflicts.map((c: any) => (
            <div key={c.key} className="conflict">
              <div><strong>{c.key}</strong> <span className="muted small">— {c.reason}</span> <Pill tone={c.status === "resolved" ? "green" : "amber"}>{c.status.replace("_", " ")}</Pill></div>
              <table><tbody>{c.options.map((o: any) => (
                <tr key={o.key} className={o.key === c.effective ? "chosen" : ""}><td><Origin origin={o.origin} /> <Source s={o.source} /></td><td>{o.title}{o.option && <span className="muted"> ({o.option})</span>}</td>
                  <td>{o.key === c.system_preferred && <Pill>system preferred: {c.system_preferred_reason}</Pill>}{o.key === c.effective && c.status === "resolved" && <Pill tone="green">chosen by {c.resolution.decided_by}</Pill>}</td>
                  <td><button onClick={() => resolve(c, o.key)}>Choose</button></td></tr>))}</tbody></table>
              {c.resolution && <p className="small">Rationale: {c.resolution.rationale}</p>}
            </div>
          ))}
        </Card>
      )}
      <Card title={`Recommendations (${data.recommendations.length})`}>
        <table><tbody>{data.recommendations.map((r: any) => (
          <tr key={r.key} className={r.conflict && !r.preferred ? "dim" : ""}><td><Origin origin={r.origin} /></td>
            <td><strong>{r.title}</strong>{r.text && <div className="small">{r.text}</div>}{r.rationale && <div className="small muted">{r.rationale}</div>}</td>
            <td><Pill tone={r.priority === "high" ? "red" : r.priority === "medium" ? "amber" : ""}>{r.priority}</Pill></td>
            <td>{r.conflict && <Pill tone="amber">{r.preferred ? "in conflict (effective)" : "in conflict"}</Pill>}</td><td><Source s={r.source} /></td></tr>))}</tbody></table>
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------ requirements
function Requirements({ id }: { id: string }) {
  const { data, error, reload } = useApi<any[]>(`/api/assessments/${id}/requirements`);
  const [busy, setBusy] = useState(false);
  if (!data) return <ErrorBox error={error} />;
  const run = async () => { setBusy(true); await api.post(`/api/assessments/${id}/process-documents`); setBusy(false); reload(); };
  return (
    <Card title={`Extracted requirements (${data.length})`} actions={<button disabled={busy} onClick={run}>{busy ? "Processing…" : "Re-process documents"}</button>}>
      <p className="muted small">Requirements are extracted with domain terminology from the selected packs; ambiguous statements generate AI-DISCOVERED clarification questions in the questionnaire.</p>
      <table><thead><tr><th>Requirement</th><th>Type / category</th><th>Domain terms</th><th>Conf.</th></tr></thead>
        <tbody>{data.map((r) => (
          <tr key={r.key}><td className="small">{r.text}<div className="muted">{r.document}</div></td><td className="small">{r.type.replace("_", "-")}<br />{r.categories.join(", ")}</td>
            <td>{r.domain_terms.map((t: any) => <span key={t.term} className="term" title={`${t.entity_type} · ${t.pack_key}`}>{t.term}</span>)}</td>
            <td>{Math.round(r.confidence * 100)}%</td></tr>))}</tbody></table>
    </Card>
  );
}

// ------------------------------------------------------------------ knowledge
function Knowledge({ id }: { id: string }) {
  const { data, error } = useApi<any>(`/api/assessments/${id}/knowledge`);
  if (!data) return <ErrorBox error={error} />;
  return (
    <div className="grid-2">
      {Object.entries(data as Record<string, any[]>).filter(([, v]) => v.length).map(([k, items]) => (
        <Card key={k} title={`${k.replace(/_/g, " ")} (${items.length})`}>
          <ul className="knowledge">{items.map((i) => <li key={i.key}><Origin origin={i.origin} /> {i.text} <Source s={i.source} /></li>)}</ul>
        </Card>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ provenance
function Provenance({ id, assessment, reload }: { id: string; assessment: any; reload: () => void }) {
  const { data, error } = useApi<any[]>(`/api/assessments/${id}/rule-sources`);
  const [type, setType] = useState("question");
  const [err, setErr] = useState<string | null>(null);
  const upgrade = async (k: string) => { try { await api.post(`/api/assessments/${id}/mappings/${k}/upgrade`); reload(); } catch (e) { setErr(errorText(e)); } };
  const types = useMemo(() => Array.from(new Set((data || []).map((r) => r.rule_type))), [data]);
  return (
    <div>
      <Card title="Domain packs used by this assessment (pinned versions)">
        <ErrorBox error={err} />
        <table><thead><tr><th>Pack</th><th>Kind</th><th>Role</th><th>Sub-domains</th><th>Pinned version</th><th>Latest published</th><th /></tr></thead>
          <tbody>{assessment.mappings.map((m: any) => (
            <tr key={m.pack_key}><td>{m.pack_name}</td><td>{m.kind}</td><td>{m.role}</td><td>{m.sub_domains.join(", ")}</td><td>v{m.version}</td>
              <td>{m.latest_published ? `v${m.latest_published}` : "–"}</td>
              <td>{m.latest_published && m.latest_published !== m.version && <button onClick={() => upgrade(m.pack_key)}>Upgrade (reviewer)</button>}</td></tr>))}</tbody></table>
      </Card>
      <Card title="Rule provenance (DomainRuleSource)" actions={<select value={type} onChange={(e) => setType(e.target.value)}>{types.map((t) => <option key={t}>{t}</option>)}</select>}>
        <ErrorBox error={error} />
        <table><thead><tr><th>Rule</th><th>Origin</th><th>Pack / version</th><th>Role</th><th>Sub-domain</th><th>Status</th><th>Merged into</th></tr></thead>
          <tbody>{(data || []).filter((r) => r.rule_type === type).map((r, i) => (
            <tr key={i} className={r.status !== "included" ? "dim" : ""}><td className="small">{r.rule_key}</td><td><Origin origin={r.origin} /></td><td className="small">{r.pack_key} {r.pack_version && `v${r.pack_version}`}</td>
              <td className="small">{r.role}</td><td className="small">{r.sub_domain || ""}</td><td><Pill tone={r.status === "included" ? "green" : r.status === "conflict" ? "amber" : ""}>{r.status}</Pill></td><td className="small">{r.merged_into || ""}</td></tr>))}</tbody></table>
      </Card>
    </div>
  );
}

function AiContext({ id }: { id: string }) {
  const { data, error } = useApi<any>(`/api/assessments/${id}/ai-context`);
  if (!data) return <ErrorBox error={error} />;
  return (
    <Card title="Domain-aware AI context (sent before every AI call)">
      <p className="muted small">Built from the confirmed classification and the pinned domain packs. Domain-pack configuration and verified client evidence take priority over general model knowledge.</p>
      <pre className="prompt">{data.system_prompt}</pre>
    </Card>
  );
}
