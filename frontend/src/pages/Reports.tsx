import { useState } from "react";
import { api, downloadFile, errorText, getUser } from "../api";
import { Card, ErrorBox, MultiCheck, Pill, useApi, useToast } from "../components";

type Generated = { content: any; method: "ai" | "template"; warnings: string[] };

const OUTLINE: Record<string, (c: any) => string[]> = {
  summary: (c) => [c.summary.title, c.summary.ask],
  opportunity: (c) => [c.opportunity.title, ...c.opportunity.challenges.map((x: any) => x.title)],
  findings: (c) => [c.findings.title, ...c.findings.key_findings.slice(0, 3)],
  approach: (c) => [c.approach.title, c.approach.stages.map((s: any) => `${s.letter} ${s.name}`).join(" → ")],
  accelerators: (c) => [c.accelerators.title, c.accelerators.items.map((a: any) => a.name + (a.live ? " (live)" : "")).join(" · ")],
  value: (c) => [c.value.title, c.value.stats.map((s: any) => `${s.value} ${s.label}`).join(" · ")],
  operating_model: (c) => [c.operating_model.title, c.operating_model.roles.map((r: any) => r.title).join(" · ")],
  roadmap: (c) => [c.roadmap.title, c.roadmap.milestones.map((m: any) => `W${m.week} ${m.label}`).join(" · ")],
  why_us: (c) => [c.why_us.title, ...c.why_us.themes.map((t: any) => t.title)],
  options: (c) => [c.options.title, c.options.items.map((o: any) => o.name + (o.recommended ? " ★" : "")).join(" · ")],
  battle_cards: (c) => ["Bid team only — battle cards", `${c.battle_cards.competitors.length} competitor types · ${c.battle_cards.objections.length} objections · ${c.battle_cards.questions.length} questions`],
};

export default function Reports({ id, assessment }: { id: string; assessment: any }) {
  const opts = useApi<any>("/api/reports/options");
  const toast = useToast();
  const canEdit = getUser().role !== "viewer";
  const [prompt, setPrompt] = useState("");
  const [sections, setSections] = useState<string[] | null>(null);
  const [useAi, setUseAi] = useState(true);
  const [gen, setGen] = useState<Generated | null>(null);
  const [busy, setBusy] = useState<"" | "gen" | "pptx" | "docx" | "xlsx">("");
  const [error, setError] = useState<unknown>(null);

  if (!opts.data) return <ErrorBox error={opts.error} />;
  const o = opts.data;
  const chosen = sections ?? o.default_sections;
  const confirmed = !!assessment.classification_confirmed_by;
  const sectionOptions = Object.entries(o.sections as Record<string, string>).map(([key, name]) => ({ key, name }));

  const generate = async () => {
    setBusy("gen"); setError(null);
    try {
      const r = await api.post<Generated>(`/api/assessments/${id}/reports/generate`, { prompt, sections: chosen, use_ai: useAi });
      setGen(r);
      toast(r.method === "ai" ? "Content generated with AI" : "Content generated from the assessment template", "ok");
    } catch (e) { setError(e); } finally { setBusy(""); }
  };
  const get = async (kind: "pptx" | "docx") => {
    setBusy(kind); setError(null);
    try {
      const body = gen ? { content: gen.content } : { prompt, sections: chosen, use_ai: false };
      await downloadFile(`/api/assessments/${id}/reports/${kind}`,
        `${assessment.client_name}_${kind === "pptx" ? "Insight_Proposal.pptx" : "Analysis_Document.docx"}`, body);
      toast(kind === "pptx" ? "PowerPoint downloaded" : "Analysis document downloaded", "ok");
    } catch (e) { setError(e); } finally { setBusy(""); }
  };
  const getXlsx = async () => {
    setBusy("xlsx"); setError(null);
    try {
      await downloadFile(`/api/assessments/${id}/questionnaire.xlsx`, `${assessment.client_name}_Assessment_Questionnaire.xlsx`);
      toast("Questionnaire downloaded", "ok");
    } catch (e) { setError(e); } finally { setBusy(""); }
  };
  const editTitle = (v: string) => gen && setGen({ ...gen, content: { ...gen.content, title: v } });

  return (
    <div className="grid2" style={{ gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 1fr)", alignItems: "start" }}>
      <Card title="1 · Describe what you need" actions={
        o.ai_available ? <Pill tone="green">✦ AI ready</Pill> : <Pill tone="amber">AI not configured — template mode</Pill>}>
        {!confirmed && <div className="notice warn">Confirm the domain classification first — reports are built from the confirmed domain packs.</div>}
        <label className="small muted" htmlFor="rp-prompt">Prompt — audience, focus, framework, sections, tone</label>
        <textarea id="rp-prompt" rows={6} value={prompt} onChange={(e) => setPrompt(e.target.value)} disabled={!canEdit}
          placeholder="e.g. Leadership bid deck for MUFG: DRIVE framework, Aurora accelerators incl. DBx Migrator, ROI and productivity value, FDE operating model, and add battle cards."
          style={{ width: "100%", marginTop: 6 }} />
        <div className="row" style={{ flexWrap: "wrap", gap: 6, margin: "8px 0 14px" }}>
          {o.example_prompts.map((p: string, i: number) => (
            <button key={i} className="fchip" onClick={() => setPrompt(p)} title={p}>Example {i + 1}</button>))}
        </div>
        <div className="small muted" style={{ marginBottom: 6 }}>Sections (the AI may refine this from your prompt)</div>
        <MultiCheck options={sectionOptions} value={chosen} onChange={setSections} columns={2} />
        <label className="check" style={{ marginTop: 10 }}>
          <input type="checkbox" checked={useAi} disabled={!o.ai_available} onChange={(e) => setUseAi(e.target.checked)} />
          Use AI ({o.ai_available ? "Claude tailors every slide to the prompt and the client documents" : "set ANTHROPIC_API_KEY on the server to enable"})
        </label>
        <div className="row" style={{ marginTop: 14, gap: 8 }}>
          <button className="primary" disabled={!canEdit || !confirmed || busy !== ""} onClick={generate}>
            {busy === "gen" ? (useAi && o.ai_available ? "Generating with AI… (up to a minute)" : "Generating…") : "✦ Generate content"}
          </button>
        </div>
        {error != null && <div className="notice err" style={{ marginTop: 10, whiteSpace: "pre-wrap" }}>{errorText(error)}</div>}
      </Card>

      <Card title="2 · Review & download" actions={gen && <Pill tone={gen.method === "ai" ? "green" : ""}>{gen.method === "ai" ? "✦ AI generated" : "Template"}</Pill>}>
        {!gen ? (
          <p className="muted small">Generate content to preview the storyline here. You can also download straight away — the deck and document are then built from the assessment data and the selected sections.</p>
        ) : (
          <>
            {gen.warnings.map((w, i) => <div key={i} className="notice warn small">{w}</div>)}
            <label className="small muted" htmlFor="rp-title">Deck title</label>
            <input id="rp-title" value={gen.content.title} onChange={(e) => editTitle(e.target.value)} style={{ width: "100%", marginBottom: 10 }} />
            <ol className="outline" style={{ paddingLeft: 18, margin: 0 }}>
              <li><b>Title</b> — {gen.content.subtitle}</li>
              {gen.content.sections.map((k: string) => {
                const [head, ...rest] = (OUTLINE[k]?.(gen.content) ?? [k]);
                return (
                  <li key={k} style={{ marginTop: 6 }}>
                    <b>{head}</b>{k === "battle_cards" && <Pill tone="red">internal</Pill>}
                    {rest.filter(Boolean).map((r: string, i: number) => <div key={i} className="small muted">{r}</div>)}
                  </li>);
              })}
              <li style={{ marginTop: 6 }}><b>{gen.content.closing.title}</b> — {gen.content.closing.message}</li>
            </ol>
          </>
        )}
        <div className="row" style={{ marginTop: 16, gap: 8, flexWrap: "wrap" }}>
          <button className="primary" disabled={!canEdit || !confirmed || busy !== ""} onClick={() => get("pptx")}>
            {busy === "pptx" ? "Building deck…" : "⬇ Download PowerPoint"}</button>
          <button disabled={!canEdit || !confirmed || busy !== ""} onClick={() => get("docx")}>
            {busy === "docx" ? "Building document…" : "⬇ Download analysis (Word)"}</button>
          <button disabled={busy !== ""} onClick={getXlsx}>
            {busy === "xlsx" ? "Building workbook…" : "⬇ Download questionnaire (Excel)"}</button>
        </div>
        <p className="small muted" style={{ marginTop: 10 }}>Insight corporate template · clickable contents and section links · slide builds and transitions · speaker notes.
          Figures marked illustrative and battle cards must be reviewed before anything is sent to the client.</p>
      </Card>
    </div>
  );
}
