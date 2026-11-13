import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { brand } from "../brand";
import { Card, Origin } from "../components";

type Step = { title: string; who: string; where: string; go: string; summary: string; points: string[]; tip?: string };

const STEPS: Step[] = [
  { title: "Create the assessment", who: "Assessor", where: "Assessments → New assessment", go: "/assessments",
    summary: "Start with the client and project name. Nothing domain-specific happens until the project is classified.",
    points: ["Enter client name, project name and an optional description.", "Click Create and classify – you land on the classification screen."] },
  { title: "Upload client documents (optional)", who: "Assessor", where: "Classification → 1. Client documents", go: "/assessments",
    summary: "Give the platform the RFP, RFI, BRD, SOW or architecture document so it can do the reading for you.",
    points: ["Upload .txt, .md, .docx or .pdf files – or paste text.", "Documents are also used later to extract requirements, raise evidenced risks and generate AI-DISCOVERED clarification questions."],
    tip: "More text = better detection. An executive summary plus requirements section is usually enough." },
  { title: "Auto-detect and confirm the domain", who: "Assessor", where: "Classification → Auto-detect domain", go: "/assessments",
    summary: "The platform suggests industry, sub-domain, technologies and project type with a confidence score and evidence.",
    points: ["Click Use suggestion to pre-fill the form, then adjust anything that is wrong – remove technologies that are only mentioned in passing.",
      "Add secondary industries for cross-industry projects (e.g. Retail + Financial Services).", "Set geography, regulatory region and data classification – these drive compliance suggestions.",
      "Click Confirm. The assessment is pinned to the current version of each domain pack."],
    tip: "AI never locks the classification: it stays a suggestion until a person confirms it." },
  { title: "Answer the tailored questionnaire", who: "Assessor", where: "Workspace → Questionnaire", go: "/assessments",
    summary: "Questions are combined from six layers and de-duplicated. Every question shows where it came from and why it applies.",
    points: ["Filter by origin or show only open questions.", "Record evidence (document, section, link) – evidence coverage is reported to leadership.",
      "Critical questions (red edge) drive the Critical gaps list.", "Accept or dismiss AI-DISCOVERED questions raised from the documents."] },
  { title: "Review risks, KPIs and compliance", who: "Assessor + Reviewer", where: "Workspace → Risks / KPIs / Compliance", go: "/assessments",
    summary: "Industry, technology and project risks are combined; KPIs and regulations are suggestions to confirm.",
    points: ["Use the risk matrix to focus on high likelihood × impact. Add project-specific risks.",
      "Confirm relevant KPIs. A target can only be saved with its client source – targets are never invented.",
      "Reviewers confirm whether each regulation applies; verifying compliance requires evidence."] },
  { title: "Shape the solution", who: "Reviewer / Architect", where: "Workspace → Architecture / Recommendations", go: "/assessments",
    summary: "Architecture components appear only when the requirements support them; conflicting recommendations from different packs are surfaced for a decision.",
    points: ["Hover a component to see why it was included; expand 'components not included' to see what was left out and why.",
      "Resolve conflicts (e.g. big-bang vs parallel run) with a written rationale – recorded with your name."] },
  { title: "Track readiness and report", who: "Everyone", where: "Workspace → Dashboard · Executive Showcase", go: "/showcase",
    summary: "Readiness is scored per area with Green / Amber / Red labels. Leadership sees the whole portfolio on the Executive Showcase.",
    points: ["Click a readiness area on the dashboard to drill into its dimensions and jump to the questions behind it.",
      "Show scoring weights to explain exactly how a score was calculated.", "Use the AI context tab to see the domain-aware instructions given to AI."] },
];

const ROLES = [
  ["Create / classify assessments, upload documents, answer questions", true, true, true, false],
  ["Accept / dismiss AI-discovered questions, confirm KPIs", true, true, true, false],
  ["Verify answers, confirm or verify regulations", true, true, false, false],
  ["Resolve conflicting recommendations, upgrade pack versions", true, true, false, false],
  ["Domain Management – create, edit, publish domain packs", true, false, false, false],
  ["View dashboards and the Executive Showcase", true, true, true, true],
] as const;

const FAQ = [
  ["Why are some questions missing compared with another project?", "Questions are filtered by sub-domain and by conditions (technology, project type, geography, data classification, answers). Only relevant questions are asked."],
  ["What does 'comparable' readiness mean?", "It uses only the global dimensions that every project shares, with fixed weights – so projects in different industries can be compared fairly. Domain-adjusted readiness adds industry and technology dimensions."],
  ["Can the AI decide that a client is compliant?", "No. The system only suggests regulations as 'potentially applicable'. Applicability is confirmed by an authorised reviewer and verification requires evidence."],
  ["A domain pack was updated – does my assessment change?", "No. Assessments keep the pack version they were classified with. A reviewer can choose to upgrade from the 'Domain packs & provenance' tab."],
  ["How do we add a new industry?", "An admin creates a domain pack (YAML) in Domain Management or the domain_packs folder, validates it and publishes it. It becomes selectable immediately – no code change."],
  ["Is AI required?", "No. Without an API key the platform uses its keyword and rules engine; with Claude enabled detection and clarification questions become richer. AI output is always reviewed by people."],
];

export default function Guide() {
  const [i, setI] = useState(0);
  const [seen, setSeen] = useState<Set<number>>(new Set([0]));
  const nav = useNavigate();
  const go = (n: number) => { const k = Math.max(0, Math.min(STEPS.length - 1, n)); setI(k); setSeen((s) => new Set(s).add(k)); };
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if ((e.target as HTMLElement).tagName === "INPUT") return; if (e.key === "ArrowRight") go(i + 1); if (e.key === "ArrowLeft") go(i - 1); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });
  const s = STEPS[i];
  return (
    <div>
      <section className="hero">
        <div className="eyebrow">How to use · {brand.product}</div>
        <h1>From client RFP to verified readiness in 7 steps</h1>
        <p>Follow the steps below. Each one tells you who does it, where to click, and what the platform does for you. Use ← → keys to move between steps.</p>
        <div className="flow" style={{ marginTop: 16 }}>
          {["Create", "Upload docs", "Detect & confirm domain", "Answer questions", "Risks · KPIs · Compliance", "Architecture", "Readiness & report"].map((n, k, arr) => (
            <span key={n} style={{ display: "contents" }}>
              <span className={`node ${k === i ? "hl" : ""}`} style={{ cursor: "pointer", background: k === i ? undefined : "rgba(255,255,255,.1)", color: "#fff", borderColor: "rgba(255,255,255,.2)" }} onClick={() => go(k)}>{k + 1}. {n}</span>
              {k < arr.length - 1 && <span className="arr" style={{ color: "#cbbfe9" }}>→</span>}
            </span>))}
        </div>
      </section>

      <div className="steps">
        <Card>
          <ol className="step-list">
            {STEPS.map((st, k) => (
              <li key={st.title} className={`${k === i ? "on" : ""} ${seen.has(k) && k !== i ? "done" : ""}`} onClick={() => go(k)}>
                <span className="step-num">{seen.has(k) && k !== i ? "✓" : k + 1}</span>
                <div><strong>{st.title}</strong><div className="small muted">{st.who}</div></div>
              </li>))}
          </ol>
        </Card>
        <Card>
          <div className="step-body page-enter" key={i}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="pill blue">Step {i + 1} of {STEPS.length} · {s.who}</span>
              <div className="progress-dots">{STEPS.map((_, k) => <i key={k} className={k <= i ? "on" : ""} />)}</div>
            </div>
            <h3 style={{ marginTop: 12 }}>{s.title}</h3>
            <p>{s.summary}</p>
            <p className="small"><strong>Where:</strong> {s.where}</p>
            <ul>{s.points.map((p) => <li key={p}>{p}</li>)}</ul>
            {s.tip && <div className="notice">💡 {s.tip}</div>}
            <div className="row" style={{ marginTop: 14 }}>
              <button disabled={i === 0} onClick={() => go(i - 1)}>← Previous</button>
              <button className="primary" onClick={() => nav(s.go)}>Take me there</button>
              <button disabled={i === STEPS.length - 1} onClick={() => go(i + 1)}>Next →</button>
            </div>
          </div>
        </Card>
      </div>

      <div className="grid-2">
        <Card title="Reading the screens">
          <h4>Question origin badges</h4>
          <table><tbody>
            {[["GLOBAL", "Asked on every project"], ["INDUSTRY", "From the selected industry pack"], ["SUB-DOMAIN", "Only for the selected sub-domain, e.g. Retail Banking"],
              ["TECHNOLOGY", "From a selected technology, e.g. Databricks"], ["PROJECT", "From the project type, e.g. Customer 360"], ["AI-DISCOVERED", "Raised from the client's documents – review before relying on it"]]
              .map(([o, d]) => <tr key={o}><td style={{ width: 130 }}><Origin origin={o} /></td><td className="small">{d}</td></tr>)}
          </tbody></table>
          <h4>Readiness status</h4>
          <table><tbody>
            <tr><td className="st-green">● Green</td><td className="small">75% or more – on track</td></tr>
            <tr><td className="st-amber">▲ Amber</td><td className="small">50–74% – attention needed</td></tr>
            <tr><td className="st-red">■ Red</td><td className="small">below 50% – at risk</td></tr>
            <tr><td className="st-grey">○ Not assessed</td><td className="small">no scored answers yet (unknown / text answers are not scored)</td></tr>
          </tbody></table>
        </Card>
        <Card title="Who can do what">
          <table>
            <thead><tr><th>Action</th><th>Admin</th><th>Reviewer</th><th>Assessor</th><th>Viewer</th></tr></thead>
            <tbody>{ROLES.map(([a, ...r]) => <tr key={a}><td className="small">{a}</td>{r.map((x, k) => <td key={k} style={{ textAlign: "center" }}>{x ? <span className="st-green">✓</span> : <span className="muted">–</span>}</td>)}</tr>)}</tbody>
          </table>
          <p className="small muted">Switch role from the top-right corner (demo identity – production uses single sign-on).</p>
        </Card>
      </div>

      <Card title="Frequently asked questions">
        <div className="faq">{FAQ.map(([q, a]) => <details key={q}><summary>{q}</summary><p>{a}</p></details>)}</div>
      </Card>
    </div>
  );
}
