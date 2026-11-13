import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { getUser, setUser, User } from "./api";
import { brand } from "./brand";
import { ToastProvider } from "./components";
import { Logo } from "./Logo";
import Assessments from "./pages/Assessments";
import AssessmentView from "./pages/AssessmentView";
import Classify from "./pages/Classify";
import DomainManagement from "./pages/DomainManagement";
import Guide from "./pages/Guide";
import Showcase from "./pages/Showcase";
import "./styles.css";

const ROLE_HELP: Record<User["role"], string> = {
  admin: "Manages domain packs + everything a reviewer can do",
  reviewer: "Verifies answers, confirms regulations, resolves conflicts",
  assessor: "Classifies projects, uploads documents, answers questions",
  viewer: "Read-only",
};

function UserSwitch() {
  const [u, setU] = useState<User>(getUser());
  const update = (n: User) => { setUser(n); setU(n); window.location.reload(); };
  return (
    <div className="user" title={`Demo identity – replace with SSO. ${ROLE_HELP[u.role]}`}>
      <span className="avatar" aria-hidden>{u.name.slice(0, 1).toUpperCase()}</span>
      <input aria-label="User name" value={u.name} onChange={(e) => setU({ ...u, name: e.target.value })} onBlur={() => update(u)} />
      <select aria-label="Role" value={u.role} onChange={(e) => update({ ...u, role: e.target.value as User["role"] })}>
        {(["admin", "reviewer", "assessor", "viewer"] as const).map((r) => <option key={r} value={r}>{r}</option>)}
      </select>
    </div>
  );
}

const NAV = [
  { to: "/showcase", label: "Executive Showcase", icon: "◆" },
  { to: "/assessments", label: "Assessments", icon: "▤" },
  { to: "/guide", label: "How to use", icon: "?" },
];

function Shell() {
  const role = getUser().role;
  const loc = useLocation();
  const crumb = loc.pathname.startsWith("/admin") ? "Administration · Domain Management"
    : loc.pathname.startsWith("/assessments/") ? "Assessments · Workspace"
    : NAV.find((n) => loc.pathname.startsWith(n.to))?.label || "";
  return (
    <div className="layout">
      <aside className="side">
        <div className="side-brand">
          <Logo />
          <div className="side-product">{brand.product}</div>
        </div>
        <nav className="side-nav">
          {NAV.map((n) => <NavLink key={n.to} to={n.to}><span className="ico" aria-hidden>{n.icon}</span>{n.label}</NavLink>)}
          {role === "admin" && <>
            <div className="side-section">Administration</div>
            <NavLink to="/admin/domains"><span className="ico" aria-hidden>⚙</span>Domain Management</NavLink>
          </>}
        </nav>
        <div className="side-foot">© {new Date().getFullYear()} {brand.company}<br /><span>{brand.tagline}</span></div>
      </aside>
      <div className="content">
        <header className="topbar">
          <div className="crumb">{crumb}</div>
          <UserSwitch />
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
