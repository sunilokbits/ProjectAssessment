import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, getUser, setUser, User } from "./api";
import { brand } from "./brand";
import { ToastProvider, useApi } from "./components";
import { Logo } from "./Logo";
import Assessments from "./pages/Assessments";
import AssessmentView from "./pages/AssessmentView";
import Classify from "./pages/Classify";
import DomainManagement from "./pages/DomainManagement";
import Guide from "./pages/Guide";
import Showcase from "./pages/Showcase";
import "./styles.css";
import "./theme-insight.css";

const ROLE_HELP: Record<User["role"], string> = {
  admin: "Manages domain packs + everything a reviewer can do",
  reviewer: "Verifies answers, confirms regulations, resolves conflicts",
  assessor: "Classifies projects, uploads documents, answers questions",
  viewer: "Read-only",
};

function UserChip() {
  const [u, setU] = useState<User>(getUser());
  const [open, setOpen] = useState(false);
  const update = (n: User) => { setUser(n); setU(n); window.location.reload(); };
  const initials = u.name.split(/[\s._-]+/).map((x) => x[0]).join("").slice(0, 2).toUpperCase() || "U";
  return (
    <div className="user-chip" title={`Demo identity – replace with SSO. ${ROLE_HELP[u.role]}`}>
      <button className="user-btn" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="avatar">{initials}</span><span className="user-name">{u.name}</span>
        <span className="role-badge">{u.role.toUpperCase()}</span>
      </button>
      {open && (
        <div className="user-pop">
          <label>Name<input value={u.name} onChange={(e) => setU({ ...u, name: e.target.value })} /></label>
          <label>Role<select value={u.role} onChange={(e) => setU({ ...u, role: e.target.value as User["role"] })}>
            {(["admin", "reviewer", "assessor", "viewer"] as const).map((r) => <option key={r} value={r}>{r}</option>)}</select></label>
          <div className="small muted">{ROLE_HELP[u.role]}</div>
          <button className="primary" onClick={() => update(u)}>Switch</button>
        </div>
      )}
    </div>
  );
}

function OnlinePill() {
  const [ok, setOk] = useState<boolean | null>(null);
  useEffect(() => {
    const check = () => api.get("/api/health").then(() => setOk(true)).catch(() => setOk(false));
    check();
    const t = setInterval(check, 30000);
    return () => clearInterval(t);
  }, []);
  return <span className={`pill-status ${ok === false ? "off" : ""}`}><i />{ok === false ? "Offline" : "Online"}</span>;
}

const PAGES: { match: (p: string) => boolean; icon: string; title: string; sub: string }[] = [
  { match: (p) => p.startsWith("/showcase"), icon: "◆", title: "Executive Showcase", sub: "Dashboard — portfolio readiness across industries, technologies and projects" },
  { match: (p) => /^\/assessments\/\d+\/classify/.test(p), icon: "✦", title: "Domain Classification", sub: "Detect and confirm industry, sub-domain, technology and project type" },
  { match: (p) => /^\/assessments\/\d+/.test(p), icon: "▤", title: "Assessment Workspace", sub: "Questionnaire, risks, KPIs, compliance, architecture and readiness" },
  { match: (p) => p.startsWith("/assessments"), icon: "▤", title: "Assessments", sub: "Create and manage domain-specific client assessments" },
  { match: (p) => p.startsWith("/guide"), icon: "?", title: "How to use", sub: "Step-by-step guide from client RFP to verified readiness" },
  { match: (p) => p.startsWith("/admin"), icon: "⚙", title: "Domain Management", sub: "Administration — domain packs, versions and publishing" },
];

function Shell() {
  const role = getUser().role;
  const loc = useLocation();
  const nav = useNavigate();
  const list = useApi<any[]>("/api/assessments", [loc.pathname]).data || [];
  const page = PAGES.find((p) => p.match(loc.pathname)) || PAGES[0];
  return (
    <div className="layout">
      <aside className="side">
        <div className="side-brand">
          <Logo light={false} size={24} />
          <div className="side-divider" />
          <div><div className="side-product">Assessment Studio</div><div className="side-sub">RFP → READINESS</div></div>
        </div>
        <nav className="side-nav">
          <NavLink to="/showcase"><span className="ico" aria-hidden>◆</span>Dashboard</NavLink>
          <div className="side-section">Workspace <span className="count">{list.length}</span></div>
          <NavLink to="/assessments" end><span className="ico" aria-hidden>▤</span>Assessments</NavLink>
          {list.slice(0, 6).map((a) => (
            <NavLink key={a.id} to={a.status === "classification_pending" ? `/assessments/${a.id}/classify` : `/assessments/${a.id}`} className="sub-link">
              <span className="ico" aria-hidden>›</span><span className="ellipsis">{a.client_name}</span>
            </NavLink>))}
          <div className="side-section">Help</div>
          <NavLink to="/guide"><span className="ico" aria-hidden>?</span>How to use</NavLink>
          {role === "admin" && <>
            <div className="side-section">Administration</div>
            <NavLink to="/admin/domains"><span className="ico" aria-hidden>⚙</span>Domain Management</NavLink>
          </>}
        </nav>
        <div className="side-foot">
          <div className="side-rainbow"><i /><i /><i /><i /><i /></div>
          © {new Date().getFullYear()} {brand.company} · {brand.product}
        </div>
      </aside>
      <div className="content">
        <header className="topbar">
          <div className="page-id">
            <span className="page-ico" aria-hidden>{page.icon}</span>
            <div><div className="page-title">{page.title}</div><div className="page-sub">{page.sub}</div></div>
          </div>
          <div className="top-actions">
            <button className="pill-btn amber" onClick={() => nav("/guide")}>▤ HOW TO USE</button>
            <button className="pill-btn blue" onClick={() => nav("/showcase")}>▸ SHOWCASE</button>
            <button className="pill-btn grad" onClick={() => nav("/assessments")}>⚡ New assessment</button>
            <OnlinePill />
            <UserChip />
          </div>
        </header>
        <main key={loc.pathname.split("/").slice(0, 3).join("/")} className="page-enter">
          <Routes>
            <Route path="/" element={<Navigate to="/showcase" replace />} />
            <Route path="/showcase" element={<Showcase />} />
            <Route path="/assessments" element={<Assessments />} />
            <Route path="/guide" element={<Guide />} />
            <Route path="/assessments/:id/classify" element={<Classify />} />
            <Route path="/assessments/:id/*" element={<AssessmentView />} />
            <Route path="/admin/domains" element={<DomainManagement />} />
          </Routes>
        </main>
        <button className="fab" title="New assessment" onClick={() => nav("/assessments")} aria-label="New assessment">⚡</button>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ToastProvider><Shell /></ToastProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
