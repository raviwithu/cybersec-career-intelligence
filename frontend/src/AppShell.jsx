import { lazy, Suspense, useEffect, useMemo, useState } from "react";

import { createProfile, fetchCategories, fetchCareerMatrix, fetchCompetencies, fetchDomains, fetchExpectations, fetchHealth, fetchIndustries, fetchLevels, fetchProfiles } from "./api";
import { Badge, ErrorState, Loading } from "./components";
import { CompetenciesPage, ComparePage, DashboardPage, DomainsPage, MatrixPage, SearchPage } from "./pages";
import CareerReadinessPage from "./CareerReadinessPage";
import AutomatedResearchPage from "./AutomatedResearchPage";
import ResearchAdminPage from "./ResearchAdminPage";
import TaxonomyManagementPage from "./TaxonomyManagementPage";
import ResearchReviewPage from "./ResearchReviewPage";
import CareerReadinessAdminPage from "./CareerReadinessAdminPage";
import IntelligencePage from "./IntelligencePage";
import ResearchIngestionPage from "./ResearchIngestionPage";
import YahooJobAlertsPage from "./YahooJobAlertsPage";
import KnowledgeTopicPage from "./KnowledgeTopicPage";
import KnowledgeReviewPage from "./KnowledgeReviewPage";
import SidebarNavigation, { findNavigationItem, getViewFromLocation } from "./SidebarNavigation";
import { useApi } from "./useApi";

// Lazy so other pages do not download the graph library.
const KnowledgeMapPage = lazy(() => import("./KnowledgeMapPage"));

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
  const [view, setView] = useState(() => getViewFromLocation());
  const [mobileOpen, setMobileOpen] = useState(false);
  useEffect(() => {
    const onLocationChange = () => setView(getViewFromLocation());
    window.addEventListener("hashchange", onLocationChange);
    window.addEventListener("popstate", onLocationChange);
    return () => { window.removeEventListener("hashchange", onLocationChange); window.removeEventListener("popstate", onLocationChange); };
  }, []);
  const [selectedDomainSlug, setSelectedDomainSlug] = useState("");
  const [selectedIndustry, setSelectedIndustry] = useState("");
  const [selectedLevel, setSelectedLevel] = useState(null);
  const [compareLevels, setCompareLevels] = useState(["senior", "architect"]);
  const [selectedCompetencyId, setSelectedCompetencyId] = useState(null);
  const [selectedTopicKey, setSelectedTopicKey] = useState("");
  const bootstrap = useApi(() => Promise.all([fetchHealth(), fetchDomains(), fetchLevels(), fetchCategories(), fetchIndustries(), fetchCareerMatrix(selectedIndustry ? { industry: selectedIndustry } : {}), fetchCompetencies({ page: 1, page_size: 1, ...(selectedIndustry ? { industry: selectedIndustry } : {}) }), fetchExpectations({ page: 1, page_size: 1, ...(selectedIndustry ? { industry: selectedIndustry } : {}) })]).then(([health, domains, levels, categories, industries, matrix, competencies, expectations]) => ({ health, domains, levels, categories, industries, matrix, competencies, expectations })), [selectedIndustry]);
  const data = bootstrap.data;
  const allDomains = useMemo(() => flattenDomains(data?.domains || []), [data?.domains]);
  const selectedDomain = allDomains.find((domain) => domain.slug === selectedDomainSlug) || null;

  function navigate(nextView, payload = null) {
    setView(nextView); setMobileOpen(false);
    if (window.location.hash !== `#${nextView}`) window.location.hash = nextView;
    if (nextView === "evidence-explorer" && payload) setSelectedCompetencyId(payload);
    if (nextView === "knowledge-topic") setSelectedTopicKey(payload || "");
    // Domains and counts load once at startup; refresh them so newly published research appears without a page reload.
    if (!nextView.startsWith("research")) bootstrap.refresh();
  }
  function selectDomain(domain) { setSelectedDomainSlug(domain.slug); setSelectedLevel(null); navigate("domains"); }
  function selectMatrixCell(domain, level) { setSelectedDomainSlug(domain.slug); setSelectedLevel(level.slug); navigate("domains"); }
  function openCompetency(id) { setSelectedCompetencyId(id); navigate("competencies"); }
  function openDomain(slug) { const domain = allDomains.find((item) => item.slug === slug); if (domain) selectDomain(domain); }
  function updateReadinessContext({ domain, level }) {
    if (domain !== undefined) setSelectedDomainSlug(domain);
    if (level !== undefined) setSelectedLevel(level || null);
  }
  if (bootstrap.loading && !data) return <div className="app-loading"><Loading label="Loading career intelligence" /></div>;
  if (bootstrap.error && !data) return <div className="app-loading"><ErrorState error={bootstrap.error} onRetry={bootstrap.reload} /></div>;

  const intelligenceViews = { "intelligence-dashboard": "dashboard", "skill-trends": "trends", "career-progression": "progression", "industry-intelligence": "industries", "industry-comparison": "industries", "competency-gaps": "gaps", "career-roadmap": "roadmap", "ask-career": "ask", "evidence-explorer": "evidence" };
  const content = view === "dashboard" ? <DashboardPage domains={data.domains} levels={data.levels} matrix={data.matrix} competencyTotal={data.competencies.meta.total} expectationTotal={data.expectations.meta.total} onNavigate={navigate} />
    : view === "readiness" ? <CareerReadinessPage domains={data.domains} levels={data.levels} categories={data.categories} industries={data.industries} selectedIndustry={selectedIndustry} onNavigate={navigate} onContextChange={updateReadinessContext} onIndustryChange={setSelectedIndustry} onCompetency={openCompetency} />
    : view === "domains" ? <DomainsPage domains={data.domains} levels={data.levels} categories={data.categories} matrix={data.matrix} selectedDomain={selectedDomain} selectedLevel={selectedLevel} selectedIndustry={selectedIndustry} onSelectDomain={selectDomain} onSelectLevel={setSelectedLevel} onCompetency={openCompetency} />
      : view === "knowledge-base" ? <KnowledgeTopicPage onNavigate={navigate} />
        : view === "knowledge-map" ? <Suspense fallback={<Loading label="Loading the knowledge map" />}><KnowledgeMapPage onNavigate={navigate} /></Suspense>
        : view === "knowledge-topic" ? <KnowledgeTopicPage topicKey={selectedTopicKey} onNavigate={navigate} />
      : view === "matrix" ? <MatrixPage matrix={data.matrix} domains={data.domains} levels={data.levels} onCell={selectMatrixCell} />
        : view === "compare" ? <ComparePage domains={allDomains} levels={data.levels} selectedDomain={selectedDomain || allDomains[0]} selectedIndustry={selectedIndustry} compareLevels={compareLevels} onDomainChange={(domain) => setSelectedDomainSlug(domain.slug)} onLevelsChange={setCompareLevels} onCompetency={openCompetency} />
          : view === "competencies" ? <CompetenciesPage domains={data.domains} levels={data.levels} categories={data.categories} selectedIndustry={selectedIndustry} selectedCompetencyId={selectedCompetencyId} onSelectCompetency={setSelectedCompetencyId} />
            : view === "search" ? <SearchPage domains={data.domains} levels={data.levels} selectedIndustry={selectedIndustry} onCompetency={openCompetency} onDomain={openDomain} />
            : view === "research" ? <ResearchAdminPage />
              : view === "research-ingestion" ? <ResearchIngestionPage onOpenReview={() => navigate("research-review")} />
                : view === "yahoo-job-alerts" ? <YahooJobAlertsPage />
                : view === "knowledge-review" ? <KnowledgeReviewPage />
                : view === "automated-research" ? <AutomatedResearchPage onOpenReview={() => navigate("research-review")} />
                  : view === "taxonomy-management" ? <TaxonomyManagementPage />
                  : view === "research-coverage" ? <AutomatedResearchPage onOpenReview={() => navigate("research-review")} initialTab="coverage" />
                    : view === "research-review" ? <ResearchReviewPage />
                      : view === "publication-history" ? <ResearchReviewPage initialView="history" />
                        : view === "career-readiness-review" ? <CareerReadinessAdminPage initialTab="review" />
                          : view === "knowledge-topics" ? <CareerReadinessAdminPage initialTab="topics" />
                            : intelligenceViews[view] ? <IntelligencePage data={data} initialView={intelligenceViews[view]} selectedCompetencyId={selectedCompetencyId} onNavigate={navigate} />
                              : <ProfilePage />;
  const currentNavigation = findNavigationItem(view);
  return <div className="app-frame">
    <SidebarNavigation view={view} onNavigate={navigate} mobileOpen={mobileOpen} onClose={() => setMobileOpen(false)} />
    <main className="main-content"><header className="topbar"><button className="mobile-menu" aria-label="Open navigation" onClick={() => setMobileOpen(true)}>☰</button><div className="breadcrumbs"><span>Research workspace</span><b>/</b><strong>{currentNavigation?.label || "Profile"}</strong></div><div className="topbar-actions"><label className="industry-scope"><span>Industry scope</span><select aria-label="Industry scope" value={selectedIndustry} onChange={(event) => setSelectedIndustry(event.target.value)}><option value="">All industries</option>{(Array.isArray(data.industries) ? data.industries : []).map((industry) => <option value={industry.slug} key={industry.id}>{industry.name}</option>)}</select></label><button className="topbar-search" onClick={() => navigate("search")}><span>⌕</span> Search the knowledge base <kbd>⌘ K</kbd></button><div className={`health-indicator ${data.health?.status === "healthy" ? "healthy" : "degraded"}`}><i />{data.health?.status === "healthy" ? "Systems healthy" : "Systems degraded"}</div></div>
</header><div className="page-content">{content}</div></main>
  </div>;
}
