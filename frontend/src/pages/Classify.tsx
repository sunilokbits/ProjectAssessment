import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, errorText } from "../api";
import { Card, ErrorBox, MultiCheck, useApi } from "../components";

type Cls = {
  primary_industry: string;
  sub_domains: string[];
  secondary_industries: { key: string; sub_domains: string[] }[];
  technologies: string[];
  project_types: string[];
  geography: string;
  regulatory_regions: string[];
  data_classifications: string[];
  stage: string;
};
const EMPTY: Cls = { primary_industry: "", sub_domains: [], secondary_industries: [], technologies: [], project_types: [],
  geography: "", regulatory_regions: [], data_classifications: [], stage: "discovery" };

function Conf({ v }: { v?: number }) {
  if (v == null) return null;
  const p = Math.round(v * 100);
  return <span className={`conf ${p >= 75 ? "hi" : p >= 45 ? "mid" : "lo"}`}>{p}% confidence</span>;
}

export default function Classify() {
  const { id } = useParams();
  const nav = useNavigate();
  const cat = useApi<any>("/api/catalog").data;
  const asmt = useApi<any>(`/api/assessments/${id}`);
  const [c, setC] = useState<Cls>(EMPTY);
  const [suggestion, setSuggestion] = useState<any>(null);
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState("");

  useEffect(() => {
    const cl = asmt.data?.classification;
    if (cl && cl.primary_industry) setC({ ...EMPTY, ...cl, geography: cl.geography || "", stage: asmt.data.stage });
    api.get(`/api/assessments/${id}/detect`).then((r) => r.suggestion && setSuggestion(r.suggestion)).catch(() => {});
  }, [asmt.data, id]);

  const industry = useMemo(() => cat?.industries.find((i: any) => i.key === c.primary_industry), [cat, c.primary_industry]);
  const techGroups = useMemo(() => {
    if (!cat) return [];
    const byKey = Object.fromEntries(cat.technologies.map((t: any) => [t.key, t]));
    const used = new Set<string>();
    const groups = Object.entries(cat.technology_categories as Record<string, string[]>).map(([g, keys]) => {
      const items = keys.filter((k) => byKey[k]).map((k) => (used.add(k), { key: k, name: byKey[k].name }));
      return { g, items };
    });
    const rest = cat.technologies.filter((t: any) => !used.has(t.key)).map((t: any) => ({ key: t.key, name: t.name }));
    if (rest.length) groups.push({ g: "Other", items: rest });
    return groups.filter((x) => x.items.length);
  }, [cat]);

  const upload = async (files: FileList | null) => {
    if (!files) return;
    setBusy("Uploading…");
    try {
      for (const f of Array.from(files)) {
        const fd = new FormData();
        fd.append("file", f);
        await api.form(`/api/assessments/${id}/documents`, fd);
      }
      asmt.reload();
    } catch (e) { setErr(errorText(e)); } finally { setBusy(""); }
  };
  const addText = async () => {
    const fd = new FormData();
    fd.append("text", text);
    fd.append("filename", "pasted-requirements.txt");
    try { await api.form(`/api/assessments/${id}/documents`, fd); setText(""); asmt.reload(); } catch (e) { setErr(errorText(e)); }
  };
  const detect = async () => {
    setBusy("Detecting domain…");
    setErr(null);
    try { setSuggestion(await api.post(`/api/assessments/${id}/detect`)); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); }
  };
  const applySuggestion = () => {
    if (!suggestion) return;
    setC({
      ...c,
      primary_industry: suggestion.industry?.key || c.primary_industry,
      sub_domains: suggestion.sub_domains.map((s: any) => s.key).slice(0, 1),
      technologies: suggestion.technologies.map((t: any) => t.key),
      project_types: suggestion.project_types.map((t: any) => t.key).slice(0, 2),
    });
  };
  const confirm = async () => {
    setErr(null);
    try {
      await api.post(`/api/assessments/${id}/classification`, { ...c, geography: c.geography || null });
      if (asmt.data?.documents?.length) await api.post(`/api/assessments/${id}/process-documents`);
      nav(`/assessments/${id}`);
    } catch (e) { setErr(errorText(e)); }
  };

  if (!cat || !asmt.data) return <p>Loading…</p>;
  const a = asmt.data;
  const sec = (key: string) => c.secondary_industries.find((s) => s.key === key);

  return (
    <div>
      <h2>{a.client_name} — {a.project_name}: domain classification</h2>
      <div className="grid-2">
        <Card title="1. Client documents (optional)">
          <p className="muted small">Upload an RFP, RFI, BRD, SOW, architecture or requirements document (txt, md, docx, pdf) to get an AI-assisted suggestion.</p>
          <input type="file" multiple onChange={(e) => upload(e.target.files)} />
          <textarea rows={4} placeholder="…or paste requirements text" value={text} onChange={(e) => setText(e.target.value)} />
          <button disabled={!text.trim()} onClick={addText}>Add text</button>
          <ul className="docs">
            {a.documents.map((d: any) => (
              <li key={d.id}>{d.filename} <span className="muted small">({d.chars.toLocaleString()} chars)</span></li>
            ))}
          </ul>
          <button className="primary" disabled={!a.documents.length || !!busy} onClick={detect}>Auto-detect domain</button>
          {busy && <span className="muted"> {busy}</span>}
          {suggestion && (
            <div className="suggestion">
              <h4>Suggested classification <span className="muted small">({suggestion.method}) – requires your confirmation</span></h4>
              {suggestion.industry ? (
                <p><strong>Industry:</strong> {suggestion.industry.name} <Conf v={suggestion.industry.confidence} />
                  <br /><span className="muted small">Evidence: {suggestion.industry.evidence.join(", ")}</span></p>
              ) : <p>No industry could be detected.</p>}
              {suggestion.industry_alternatives?.length > 0 && (
                <p className="small">Alternatives: {suggestion.industry_alternatives.map((x: any) => x.name).join(", ")}</p>)}
              <p><strong>Sub-domain:</strong> {suggestion.sub_domains.map((s: any) => <span key={s.key}>{s.name} <Conf v={s.confidence} /> </span>)}</p>
              <p><strong>Technology:</strong> {suggestion.technologies.map((s: any) => s.name).join(" + ") || "–"}</p>
              <p><strong>Project type:</strong> {suggestion.project_types.map((s: any) => s.name).join(" / ") || "–"}</p>
              <button onClick={applySuggestion}>Use suggestion in form (you can still change it)</button>
            </div>
          )}
        </Card>

        <Card title="2. Confirm classification">
          <div className="form">
            <label>Primary industry / domain *
              <select value={c.primary_industry} onChange={(e) => setC({ ...c, primary_industry: e.target.value, sub_domains: [] })}>
                <option value="">— select —</option>
                {cat.industries.map((i: any) => <option key={i.key} value={i.key}>{i.name}</option>)}
              </select>
            </label>
            {industry && (
              <fieldset><legend>Sub-domain(s)</legend>
                <MultiCheck options={industry.sub_domains} value={c.sub_domains} onChange={(v) => setC({ ...c, sub_domains: v })} />
              </fieldset>
            )}
            <fieldset><legend>Secondary / cross-industry domains</legend>
              <MultiCheck columns={3}
                options={cat.industries.filter((i: any) => i.key !== c.primary_industry)}
                value={c.secondary_industries.map((s) => s.key)}
                onChange={(keys) => setC({ ...c, secondary_industries: keys.map((k) => sec(k) || { key: k, sub_domains: [] }) })} />
              {c.secondary_industries.map((s) => {
                const ind = cat.industries.find((i: any) => i.key === s.key);
                return ind?.sub_domains.length ? (
                  <div key={s.key} className="nested"><span className="small">{ind.name} sub-domains:</span>
                    <MultiCheck options={ind.sub_domains} value={s.sub_domains}
                      onChange={(v) => setC({ ...c, secondary_industries: c.secondary_industries.map((x) => x.key === s.key ? { ...x, sub_domains: v } : x) })} />
                  </div>) : null;
              })}
            </fieldset>
            <fieldset><legend>Technology domains (multiple)</legend>
              {techGroups.map(({ g, items }) => (
                <div key={g}><div className="small muted">{g}</div>
                  <MultiCheck columns={4} options={items} value={c.technologies} onChange={(v) => setC({ ...c, technologies: v })} /></div>
              ))}
            </fieldset>
            <fieldset><legend>Project type</legend>
              <MultiCheck options={cat.project_types} value={c.project_types} onChange={(v) => setC({ ...c, project_types: v })} />
            </fieldset>
            <div className="row">
              <label>Geography / country
                <select value={c.geography} onChange={(e) => setC({ ...c, geography: e.target.value })}>
                  <option value="">— not specified —</option>
                  {cat.geographies.map((g: any) => <option key={g.code} value={g.code}>{g.name}</option>)}
                </select>
              </label>
              <label>Assessment stage
                <select value={c.stage} onChange={(e) => setC({ ...c, stage: e.target.value })}>
                  {cat.stages.map((s: any) => <option key={s.key} value={s.key}>{s.name}</option>)}
                </select>
              </label>
            </div>
            <fieldset><legend>Regulatory region(s)</legend>
              <MultiCheck columns={4} options={cat.regulatory_regions.map((r: any) => ({ key: r.code, name: r.name }))}
                value={c.regulatory_regions} onChange={(v) => setC({ ...c, regulatory_regions: v })} />
            </fieldset>
            <fieldset><legend>Data classification</legend>
              <MultiCheck columns={3} options={cat.data_classifications} value={c.data_classifications}
                onChange={(v) => setC({ ...c, data_classifications: v })} />
            </fieldset>
            <button className="primary" disabled={!c.primary_industry} onClick={confirm}>Confirm classification and start assessment</button>
            <ErrorBox error={err} />
          </div>
        </Card>
      </div>
    </div>
  );
}
