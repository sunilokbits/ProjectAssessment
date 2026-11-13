import { useEffect, useMemo, useState } from "react";
import YAML from "yaml";
import { api, errorText, getUser } from "../api";
import { Card, ErrorBox, Pill, useApi } from "../components";

const KINDS = [["industry", "Industries"], ["technology", "Technology domains"], ["project_type", "Project types"], ["global", "Global"]];

export default function DomainManagement() {
  const packs = useApi<any[]>("/api/admin/domain-packs");
  const schema = useApi<any>("/api/admin/domain-packs/schema").data;
  const [kind, setKind] = useState("industry");
  const [sel, setSel] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  if (getUser().role !== "admin") return <ErrorBox error="Domain Management requires the admin role." />;
  const list = (packs.data || []).filter((p) => p.kind === kind && (p.name + p.key).toLowerCase().includes(q.toLowerCase()));
  const pack = (packs.data || []).find((p) => p.key === sel);

  const sync = async () => {
    try {
      const r = await api.post("/api/admin/domain-packs/sync");
      const errs = Object.entries(r.errors as Record<string, any[]>).map(([p, es]) => `${p}:\n` + es.map((e) => `  - ${e.location}: ${e.message}`).join("\n")).join("\n");
      setMsg(`Imported ${r.imported.length}, unchanged ${r.unchanged.length}, invalid ${Object.keys(r.errors).length}`);
      setErr(errs || null);
      packs.reload();
    } catch (e) { setErr(errorText(e)); }
  };

  return (
    <div className="admin">
      <div className="title-row"><h2>Administration → Domain Management</h2>
        <div className="row">
          <button onClick={sync} title="Import new / changed pack folders from domain_packs/">Rescan domain_packs folder</button>
          {schema && <a className="button" download="domain_pack.schema.json"
            href={URL.createObjectURL(new Blob([JSON.stringify(schema.json_schema, null, 2)], { type: "application/json" }))}>Download JSON Schema</a>}
        </div>
      </div>
      {msg && <div className="notice">{msg}</div>}
      <ErrorBox error={err || packs.error} />
      <div className="admin-grid">
        <aside className="card">
          <div className="seg">{KINDS.map(([k, l]) => <button key={k} className={kind === k ? "on" : ""} onClick={() => setKind(k)}>{l}</button>)}</div>
          <input placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)} />
          <ul className="pack-list">
            {list.map((p) => (
              <li key={p.key} className={sel === p.key ? "sel" : ""} onClick={() => setSel(p.key)}>
                <span>{p.name}</span>
                <span>{!p.enabled && <Pill tone="red">disabled</Pill>}{p.latest_published ? <Pill tone="green">v{p.latest_published}</Pill> : <Pill tone="amber">draft</Pill>}</span>
              </li>
            ))}
          </ul>
          <CreateDomain onCreated={(k) => { packs.reload(); setSel(k); }} kind={kind} />
          <UploadPack onDone={(k) => { packs.reload(); if (k) setSel(k); }} />
        </aside>
        <div>{pack ? <PackDetail pack={pack} sections={schema?.sections || []} reload={packs.reload} /> : <Card><p className="muted">Select a domain pack.</p></Card>}</div>
      </div>
    </div>
  );
}

function CreateDomain({ onCreated, kind }: { onCreated: (k: string) => void; kind: string }) {
  const [f, setF] = useState({ key: "", name: "", description: "", subs: "" });
  const [err, setErr] = useState<string | null>(null);
  const create = async () => {
    const sub_domains = f.subs.split(",").map((s) => s.trim()).filter(Boolean).map((n) => ({ key: n.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, ""), name: n }));
    try { await api.post("/api/admin/domain-packs", { key: f.key, name: f.name, kind, description: f.description, sub_domains }); setF({ key: "", name: "", description: "", subs: "" }); setErr(null); onCreated(f.key); }
    catch (e) { setErr(errorText(e)); }
  };
  return (
    <details><summary>Create {kind.replace("_", " ")} domain</summary>
      <div className="form">
        <input placeholder="key (e.g. aviation)" value={f.key} onChange={(e) => setF({ ...f, key: e.target.value })} />
        <input placeholder="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <input placeholder="Description" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
        {kind === "industry" && <input placeholder="Sub-domains (comma separated)" value={f.subs} onChange={(e) => setF({ ...f, subs: e.target.value })} />}
        <button disabled={!f.key || !f.name} onClick={create}>Create draft v0.1.0</button>
        <ErrorBox error={err} />
      </div>
    </details>
  );
}

function UploadPack({ onDone }: { onDone: (k?: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [res, setRes] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const send = async (validateOnly: boolean) => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("validate_only", String(validateOnly));
    try {
      const r = await api.form("/api/admin/domain-packs/upload", fd);
      setErr(null);
      setRes(validateOnly ? `Valid: ${r.key} v${r.version}${r.warnings?.length ? " (warnings: " + r.warnings.join("; ") + ")" : ""}` : `Uploaded ${r.pack_key} v${r.version} as ${r.status}`);
      if (!validateOnly) onDone(r.pack_key);
    } catch (e) { setRes(null); setErr(errorText(e)); }
  };
  return (
    <details><summary>Upload domain pack (YAML / JSON bundle or .zip)</summary>
      <div className="form">
        <input type="file" accept=".yaml,.yml,.json,.zip" onChange={(e) => setFile(e.target.files?.[0] || null)} />
        <div className="row"><button disabled={!file} onClick={() => send(true)}>Validate</button><button disabled={!file} className="primary" onClick={() => send(false)}>Upload as draft</button></div>
        {res && <div className="notice">{res}</div>}
        <ErrorBox error={err} />
      </div>
    </details>
  );
}

function PackDetail({ pack, sections, reload }: { pack: any; sections: string[]; reload: () => void }) {
  const [ver, setVer] = useState<string>(pack.versions[0]?.version);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => setVer(pack.versions[0]?.version), [pack.key]);
  const v = pack.versions.find((x: any) => x.version === ver);
  const act = async (path: string, method: "post" | "del" | "patch" = "post", body?: any) => {
    try { await (method === "del" ? api.del(path) : (api as any)[method](path, body)); setErr(null); reload(); } catch (e) { setErr(errorText(e)); }
  };
  const base = `/api/admin/domain-packs/${pack.key}`;
  return (
    <div>
      <Card title={<>{pack.name} <span className="muted small">({pack.key} · {pack.kind}{pack.builtin ? " · built-in" : ""})</span></>}
        actions={pack.kind !== "global" && <button onClick={() => act(base, "patch", { enabled: !pack.enabled })}>{pack.enabled ? "Disable domain" : "Enable domain"}</button>}>
        <p className="small">{pack.description}</p>
        {pack.sub_domains.length > 0 && <p className="small">Sub-domains: {pack.sub_domains.join(", ")}</p>}
        <ErrorBox error={err} />
        <table>
          <thead><tr><th>Version</th><th>Status</th><th>Content</th><th>Used by</th><th>Created / published</th><th>Actions</th></tr></thead>
          <tbody>{pack.versions.map((x: any) => (
            <tr key={x.id} className={x.version === ver ? "chosen" : ""} onClick={() => setVer(x.version)}>
              <td>v{x.version}</td>
              <td><Pill tone={x.status === "published" ? "green" : x.status === "draft" ? "amber" : ""}>{x.status}</Pill></td>
              <td className="small">{Object.entries(x.counts).filter(([, n]) => n).map(([k, n]) => `${n} ${k}`).join(", ")}</td>
              <td>{x.assessments_using} assessments</td>
              <td className="small">{x.created_by} · {x.published_by ? `published by ${x.published_by}` : ""}</td>
              <td className="row" onClick={(e) => e.stopPropagation()}>
                {x.status !== "published" && x.status !== "archived" && <button className="primary" onClick={() => act(`${base}/versions/${x.version}/publish`)}>Publish</button>}
                {x.status === "published" && <button onClick={() => act(`${base}/versions/${x.version}/unpublish`)}>Unpublish</button>}
                <button onClick={() => act(`${base}/versions/${x.version}/clone`)}>New version from this</button>
                <a className="button" href={`${base}/versions/${x.version}/export`} onClick={async (e) => {
                  e.preventDefault();
                  const t = await api.get<string>(`${base}/versions/${x.version}/export`);
                  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([t])); a.download = `${pack.key}-${x.version}.yaml`; a.click();
                }}>Export</a>
                {x.status === "draft" && !x.assessments_using && <button onClick={() => confirm(`Delete draft v${x.version}?`) && act(`${base}/versions/${x.version}`, "del")}>Delete draft</button>}
              </td>
            </tr>))}</tbody>
        </table>
        <p className="muted small">Published versions are immutable. Existing assessments keep the version they were classified with.</p>
      </Card>
      {v && <SectionEditor packKey={pack.key} version={v} sections={sections} onSaved={reload} />}
    </div>
  );
}

const SECTION_LABELS: Record<string, string> = {
  domain: "Domain & sub-domains", questions: "Questions", risks: "Risks", kpis: "KPIs", compliance: "Compliance references",
  terminology: "Terminology", architecture_patterns: "Architecture patterns", recommendations: "Recommendations",
  knowledge: "NFRs / assumptions / dependencies / AI", scoring: "Scoring dimensions", prompts: "AI prompt additions",
};

function SectionEditor({ packKey, version, sections, onSaved }: { packKey: string; version: any; sections: string[]; onSaved: () => void }) {
  const full = useApi<any>(`/api/admin/domain-packs/${packKey}/versions/${version.version}`, [version.checksum]);
  const [section, setSection] = useState("questions");
  const [text, setText] = useState("");
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const editable = version.status === "draft";
  const content = full.data?.content;
  useEffect(() => {
    if (content) setText(YAML.stringify(content[section] ?? (section === "knowledge" || section === "scoring" || section === "prompts" ? {} : []), { lineWidth: 0 }));
    setResult(null);
  }, [content, section]);
  const parsed = useMemo(() => { try { return { v: YAML.parse(text) }; } catch (e: any) { return { e: e.message as string }; } }, [text]);

  const validate = async () => {
    if ("e" in parsed) return setResult({ ok: false, text: `YAML parse error: ${parsed.e}` });
    const r = await api.post("/api/admin/domain-packs/validate", { content: { ...content, [section]: parsed.v } });
    setResult(r.valid ? { ok: true, text: `Valid${r.warnings.length ? " — warnings: " + r.warnings.join("; ") : ""}` }
      : { ok: false, text: r.errors.map((e: any) => `${e.location}: ${e.message}`).join("\n") });
  };
  const save = async () => {
    if ("e" in parsed) return setResult({ ok: false, text: `YAML parse error: ${parsed.e}` });
    try { await api.put(`/api/admin/domain-packs/${packKey}/versions/${version.version}/sections/${section}`, { value: parsed.v }); setResult({ ok: true, text: "Saved." }); onSaved(); full.reload(); }
    catch (e) { setResult({ ok: false, text: errorText(e) }); }
  };
  return (
    <Card title={`Configure v${version.version} ${editable ? "(draft – editable)" : `(${version.status} – read-only; create a new version to edit)`}`}>
      <div className="seg wrap">{sections.map((s) => <button key={s} className={section === s ? "on" : ""} onClick={() => setSection(s)}>{SECTION_LABELS[s] || s}</button>)}</div>
      <textarea className="code" rows={24} value={text} readOnly={!editable} onChange={(e) => setText(e.target.value)} spellCheck={false} />
      <div className="row">
        <button onClick={validate}>Validate</button>
        {editable && <button className="primary" onClick={save}>Save section</button>}
        <span className="muted small">Edits are validated against the Domain Pack schema (Pydantic) before saving.</span>
      </div>
      {result && <pre className={result.ok ? "ok" : "error"}>{result.text}</pre>}
    </Card>
  );
}
