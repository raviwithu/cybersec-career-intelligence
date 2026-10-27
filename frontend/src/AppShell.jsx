import { useEffect, useMemo, useState } from "react";

import { createProfile, fetchCategories, fetchCareerMatrix, fetchCompetencies, fetchDomains, fetchExpectations, fetchHealth, fetchLevels, fetchProfiles } from "./api";
import { Badge, ErrorState, Loading } from "./components";
import { CompetenciesPage, ComparePage, DashboardPage, DomainsPage, MatrixPage, SearchPage } from "./pages";
import ResearchAdminPage from "./ResearchAdminPage";
import { useApi } from "./useApi";

const navigation = [
  { id: "dashboard", label: "Overview", icon: "⌂" },
  { id: "domains", label: "Domain Explorer", icon: "◈" },
  { id: "matrix", label: "Career Matrix", icon: "▦" },
  { id: "compare", label: "Compare levels", icon: "⇄" },
  { id: "competencies", label: "Competencies", icon: "◎" },
  { id: "search", label: "Global search", icon: "⌕" },
  { id: "research", label: "Research admin", icon: "✦" },
];

function flattenDomains(domains) { return domains.flatMap((domain) => [domain, ...(domain.children || [])]); }

function ProfilePage() {
  const [form, setForm] = useState({ full_name: "", target_role: "", skills: "" });
  const [profiles, setProfiles] = useState([]);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  async function load() { try { setProfiles(await fetchProfiles()); } catch (requestError) { setError(requestError); } }
  useEffect(() => { load(); }, []);
  async function submit(event) {
    event.preventDefault(); setSaving(true);
    try { await createProfile({ full_name: form.full_name.trim(), target_role: form.target_role.trim(), skills: form.skills.split(",").map((skill) => skill.trim()).filter(Boolean) }); setForm({ full_name: "", target_role: "", skills: "" }); await load(); } catch (requestError) { setError(requestError); } finally { setSaving(false); }
  }
  return <><div className="page-header"><div><p className="eyebrow">PHASE 1 / PROFILE</p><h1>Your career baseline</h1><p className="page-description">Keep a lightweight profile alongside the consolidated knowledge base.</p></div></div>{error && <ErrorState error={error} onRetry={load} />}<div className="profile-layout"><form className="panel profile-form" onSubmit={submit}><p className="eyebrow">SAVE A PROFILE</p><label>Full name<input required value={form.full_name} onChange={(event) => setForm({ ...form, full_name: event.target.value })} /></label><label>Target role<input required value={form.target_role} placeholder="e.g. Product Security Engineer" onChange={(event) => setForm({ ...form, target_role: event.target.value })} /></label><label>Skills <span className="hint">comma separated</span><input value={form.skills} placeholder="Python, threat modeling, cloud security" onChange={(event) => setForm({ ...form, skills: event.target.value })} /></label><button className="button" disabled={saving}>{saving ? "Saving…" : "Save profile"}</button></form><section className="panel"><div className="panel-title-row"><div><p className="eyebrow">SAVED SIGNALS</p><h2>Profiles</h2></div><Badge>{profiles.length}</Badge></div>{profiles.length ? profiles.map((profile) => <div className="profile-row" key={profile.id}><div><strong>{profile.full_name}</strong><span>{profile.target_role}</span></div><div className="tag-list">{profile.skills.map((skill) => <Badge key={skill}>{skill}</Badge>)}</div></div>) : <p className="muted-copy">No profiles saved yet.</p>}</section></div></>;
}

export default function AppShell() {
  const [view, setView] = useState("dashboard");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [selectedDomainSlug, setSelectedDomainSlug] = useState("");
  const [selectedLevel, setSelectedLevel] = useState(null);
  const [compareLevels, setCompareLevels] = useState(["senior", "architect"]);
  const [selectedCompetencyId, setSelectedCompetencyId] = useState(null);
  const bootstrap = useApi(() => Promise.all([fetchHealth(), fetchDomains(), fetchLevels(), fetchCategories(), fetchCareerMatrix(), fetchCompetencies({ page: 1, page_size: 1 }), fetchExpectations({ page: 1, page_size: 1 })]).then(([health, domains, levels, categories, matrix, competencies, expectations]) => ({ health, domains, levels, categories, matrix, competencies, expectations })), []);
  const data = bootstrap.data;
  const allDomains = useMemo(() => flattenDomains(data?.domains || []), [data?.domains]);
  const selectedDomain = allDomains.find((domain) => domain.slug === selectedDomainSlug) || null;

  function navigate(nextView) { setView(nextView); setMobileOpen(false); }
  function selectDomain(domain) { setSelectedDomainSlug(domain.slug); setSelectedLevel(null); navigate("domains"); }
  function selectMatrixCell(domain, level) { setSelectedDomainSlug(domain.slug); setSelectedLevel(level.slug); navigate("domains"); }
  function openCompetency(id) { setSelectedCompetencyId(id); navigate("competencies"); }
  function openDomain(slug) { const domain = allDomains.find((item) => item.slug === slug); if (domain) selectDomain(domain); }
  if (bootstrap.loading && !data) return <div className="app-loading"><Loading label="Loading career intelligence" /></div>;
  if (bootstrap.error && !data) return <div className="app-loading"><ErrorState error={bootstrap.error} onRetry={bootstrap.reload} /></div>;

  const content = view === "dashboard" ? <DashboardPage domains={data.domains} levels={data.levels} matrix={data.matrix} competencyTotal={data.competencies.meta.total} expectationTotal={data.expectations.meta.total} onNavigate={navigate} />
    : view === "domains" ? <DomainsPage domains={data.domains} levels={data.levels} categories={data.categories} matrix={data.matrix} selectedDomain={selectedDomain} selectedLevel={selectedLevel} onSelectDomain={selectDomain} onSelectLevel={setSelectedLevel} onCompetency={openCompetency} />
      : view === "matrix" ? <MatrixPage matrix={data.matrix} domains={data.domains} levels={data.levels} onCell={selectMatrixCell} />
        : view === "compare" ? <ComparePage domains={allDomains} levels={data.levels} selectedDomain={selectedDomain || allDomains[0]} compareLevels={compareLevels} onDomainChange={(domain) => setSelectedDomainSlug(domain.slug)} onLevelsChange={setCompareLevels} onCompetency={openCompetency} />
          : view === "competencies" ? <CompetenciesPage domains={data.domains} levels={data.levels} categories={data.categories} selectedCompetencyId={selectedCompetencyId} onSelectCompetency={setSelectedCompetencyId} />
            : view === "search" ? <SearchPage domains={data.domains} levels={data.levels} onCompetency={openCompetency} onDomain={openDomain} />
            : view === "research" ? <ResearchAdminPage />
              : <ProfilePage />;
  return <div className="app-frame">
    <aside className={`sidebar ${mobileOpen ? "open" : ""}`}><div className="brand"><div className="brand-mark">C<span>·</span></div><div><strong>CyberSec</strong><small>Career Intelligence</small></div></div><div className="sidebar-section"><span className="sidebar-label">WORKSPACE</span><nav>{navigation.map((item) => <button className={view === item.id ? "active" : ""} key={item.id} onClick={() => navigate(item.id)}><span>{item.icon}</span>{item.label}</button>)}</nav></div><div className="sidebar-footer"><button className={`profile-nav ${view === "profile" ? "active" : ""}`} onClick={() => navigate("profile")}><span className="avatar">CI</span><span><strong>My profile</strong><small>Phase 1 baseline</small></span><span>→</span></button><div className="version-label">KNOWLEDGE BASE · PHASE 4</div></div></aside>
    {mobileOpen && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}
    <main className="main-content"><header className="topbar"><button className="mobile-menu" aria-label="Open navigation" onClick={() => setMobileOpen(true)}>☰</button><div className="breadcrumbs"><span>Research workspace</span><b>/</b><strong>{navigation.find((item) => item.id === view)?.label || "Profile"}</strong></div><div className="topbar-actions"><button className="topbar-search" onClick={() => navigate("search")}><span>⌕</span> Search the knowledge base <kbd>⌘ K</kbd></button><div className={`health-indicator ${data.health?.status === "healthy" ? "healthy" : "degraded"}`}><i />{data.health?.status === "healthy" ? "Systems healthy" : "Systems degraded"}</div></div></header><div className="page-content">{content}</div></main>
  </div>;
}
