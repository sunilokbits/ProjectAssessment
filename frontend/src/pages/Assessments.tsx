import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, errorText } from "../api";
import { Card, ErrorBox, Pill, useApi } from "../components";

export default function Assessments() {
  const { data, error } = useApi<any[]>("/api/assessments");
  const [form, setForm] = useState({ client_name: "", project_name: "", description: "" });
  const [err, setErr] = useState<string | null>(null);
  const nav = useNavigate();

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const a = await api.post("/api/assessments", form);
      nav(`/assessments/${a.id}/classify`);
    } catch (x) {
      setErr(errorText(x));
    }
  };

  return (
    <div className="grid-2">
      <Card title="Assessments">
        <ErrorBox error={error} />
        <table>
          <thead>
            <tr><th>Client</th><th>Project</th><th>Industry</th><th>Stage</th><th>Status</th></tr>
          </thead>
          <tbody>
            {(data || []).map((a) => (
              <tr key={a.id}>
                <td>{a.client_name}</td>
                <td>
                  <Link to={a.status === "classification_pending" ? `/assessments/${a.id}/classify` : `/assessments/${a.id}`}>
                    {a.project_name}
                  </Link>
                </td>
                <td>{a.mappings.find((m: any) => m.role === "primary")?.pack_name || <span className="muted">not classified</span>}</td>
                <td>{a.stage}</td>
                <td><Pill tone={a.status === "classification_pending" ? "amber" : "green"}>{a.status.replace("_", " ")}</Pill></td>
              </tr>
            ))}
            {data && data.length === 0 && <tr><td colSpan={5} className="muted">No assessments yet.</td></tr>}
          </tbody>
        </table>
      </Card>
      <Card title="New assessment">
        <form onSubmit={create} className="form">
          <label>Client name<input required value={form.client_name} onChange={(e) => setForm({ ...form, client_name: e.target.value })} /></label>
          <label>Project name<input required value={form.project_name} onChange={(e) => setForm({ ...form, project_name: e.target.value })} /></label>
          <label>Description<textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
          <p className="muted small">Next you will select (or auto-detect from client documents) the industry, sub-domain, technology and project type. The detailed assessment starts only after the classification is confirmed.</p>
          <button className="primary">Create and classify →</button>
          <ErrorBox error={err} />
        </form>
      </Card>
    </div>
  );
}
