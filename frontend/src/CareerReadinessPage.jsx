import { useEffect, useMemo, useRef, useState } from "react";

import { fetchExpectations, fetchIntelligenceEvidence } from "./api";
import { Badge, EmptyState, ErrorState, Loading, PageHeader } from "./components";

const PRIORITY_RANK = { essential: 0, important: 1, useful: 2 };
const DEFAULT_FILTERS = { domain: "embedded-systems-security", subdomain: "", career_level: "senior", industry: "", category: "", importance: "", proficiency: "" };

function clean(value) {
  return typeof value === "string" ? value.trim() : "";
}

function formatDate(value) {
  if (!value) return "Date unavailable";
  return new Date(value).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function expectationText(expectation) {
  return clean(expectation.expectation_description) || clean(expectation.practical_capability) || "Published expectation details are not available for this competency.";
}

function sourceCount(expectation) {
  return expectation.supporting_sources?.length || 0;
}

function categoryLabel(category) {
  return category?.name || "Uncategorized";
}

function sourceEvidence(expectation) {
  return (expectation.supporting_sources || []).map(({ source, supporting_excerpt }) => ({
    source_title: source.source_title,
    source_url: source.source_url,
    research_date: source.collected_at,
    excerpt: supporting_excerpt,
    publication_version: null,
  }));
}

function readinessSentence(count, sourceCountValue, levelName, domainName, industryName) {
  if (!count) return `There are no published expectations for ${levelName || "this level"} in ${domainName || "this domain"} yet.`;
  const evidence = sourceCountValue ? ` ${sourceCountValue} research source${sourceCountValue === 1 ? " supports" : "s support"} the current view.` : " Evidence is limited, so missing records should not be read as missing capability.";
  return `${count} expectation${count === 1 ? " is" : "s are"} currently mapped to ${levelName || "the selected level"} in ${domainName || "this domain"}${industryName ? ` for ${industryName}` : ""}.${evidence}`;
}

function optionLabel(item) {
  return item.parent_id ? `↳ ${item.name}` : item.name;
}

export default function CareerReadinessPage({ domains, levels, categories, industries, selectedIndustry, onNavigate, onContextChange, onIndustryChange, onCompetency }) {
  const [filters, setFilters] = useState({ ...DEFAULT_FILTERS, industry: selectedIndustry || "" });
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [activeCategory, setActiveCategory] = useState("");
  const [showAllPriorities, setShowAllPriorities] = useState(false);
  const [expandedId, setExpandedId] = useState(null);
  const [evidence, setEvidence] = useState(null);
  const [loadingEvidence, setLoadingEvidence] = useState(false);
  const [evidenceError, setEvidenceError] = useState(null);
  const [summaryExpanded, setSummaryExpanded] = useState(false);
  const [visibleExpectationCount, setVisibleExpectationCount] = useState(12);
  const closeButtonRef = useRef(null);
  const evidenceTriggerRef = useRef(null);

  const roots = domains || [];
  const selectedRoot = roots.find((domain) => domain.slug === filters.domain);
  const subdomains = selectedRoot?.children || [];
  const selectedDomain = [...roots, ...roots.flatMap((domain) => domain.children || [])].find((domain) => domain.slug === (filters.subdomain || filters.domain));
  const selectedLevel = levels.find((level) => level.slug === filters.career_level);
  const selectedIndustryItem = industries.find((industry) => industry.slug === filters.industry);
  const effectiveDomain = filters.subdomain || filters.domain;

  useEffect(() => {
    if (selectedIndustry !== undefined && selectedIndustry !== filters.industry) {
      setFilters((current) => ({ ...current, industry: selectedIndustry || "" }));
    }
  }, [selectedIndustry]);

  useEffect(() => {
    if (filters.subdomain && !subdomains.some((domain) => domain.slug === filters.subdomain)) {
      setFilters((current) => ({ ...current, subdomain: "" }));
    }
  }, [filters.domain, filters.subdomain, subdomains]);

  const query = useMemo(() => ({
    ...(effectiveDomain ? { domain: effectiveDomain } : {}),
    ...(filters.career_level ? { level: filters.career_level } : {}),
    ...(filters.industry ? { industry: filters.industry } : {}),
    ...(filters.category ? { category: filters.category } : {}),
    ...(filters.importance ? { importance: filters.importance } : {}),
    ...(filters.proficiency ? { proficiency: filters.proficiency } : {}),
    page: 1,
    page_size: 100,
  }), [effectiveDomain, filters.career_level, filters.industry, filters.category, filters.importance, filters.proficiency]);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [requestVersion, setRequestVersion] = useState(0);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError(null);
    fetchExpectations(query).then((next) => {
      if (current) setResult(next);
    }).catch((requestError) => {
      if (current) setError(requestError);
    }).finally(() => {
      if (current) setLoading(false);
    });
    return () => { current = false; };
  }, [query, requestVersion]);

  const expectations = result?.items || [];
  function retryLoad() { setRequestVersion((version) => version + 1); }
  const filteredExpectations = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return expectations;
    return expectations.filter((expectation) => [expectation.competency?.name, expectation.competency?.description, expectation.expectation_description, expectation.technical_knowledge, expectation.practical_capability, expectation.tools_technologies].some((value) => clean(value).toLowerCase().includes(term)));
  }, [expectations, search]);
  const categoriesWithData = useMemo(() => categories.filter((category) => filteredExpectations.some((expectation) => expectation.competency?.category?.slug === category.slug)), [categories, filteredExpectations]);

  useEffect(() => {
    if (activeCategory && !categoriesWithData.some((category) => category.slug === activeCategory)) setActiveCategory("");
  }, [activeCategory, categoriesWithData]);

  useEffect(() => {
    setVisibleExpectationCount(12);
  }, [activeCategory, search, query]);

  const categoryExpectations = activeCategory ? filteredExpectations.filter((expectation) => expectation.competency?.category?.slug === activeCategory) : filteredExpectations;
  const evidenceSourceCount = new Set(filteredExpectations.flatMap((expectation) => (expectation.supporting_sources || []).map(({ source }) => source.id))).size;
  const priorities = useMemo(() => {
    const unique = new Map();
    filteredExpectations.forEach((expectation) => {
      const competency = expectation.competency;
      if (!competency || unique.has(competency.id)) return;
      unique.set(competency.id, expectation);
    });
    return [...unique.values()].sort((left, right) => (PRIORITY_RANK[left.importance] ?? 3) - (PRIORITY_RANK[right.importance] ?? 3) || left.competency.name.localeCompare(right.competency.name));
  }, [filteredExpectations]);
  const visiblePriorities = showAllPriorities ? priorities : priorities.slice(0, 6);

  function updateFilter(key, value) {
    setFilters((current) => {
      const next = { ...current, [key]: value };
      if (key === "domain") next.subdomain = "";
      return next;
    });
    if (key === "industry") onIndustryChange?.(value);
    if (key === "domain") onContextChange?.({ domain: value, level: filters.career_level });
    if (key === "career_level") onContextChange?.({ domain: effectiveDomain, level: value });
  }

  function clearFilters() {
    setFilters({ domain: "", subdomain: "", career_level: "", industry: "", category: "", importance: "", proficiency: "" });
    setSearch("");
    setActiveCategory("");
    onContextChange?.({ domain: "", level: null });
    onIndustryChange?.("");
  }

  async function openEvidence(expectation, trigger) {
    evidenceTriggerRef.current = trigger || document.activeElement;
    setEvidence({ expectation, items: sourceEvidence(expectation) });
    setEvidenceError(null);
    setLoadingEvidence(true);
    try {
      const response = await fetchIntelligenceEvidence({ competency_id: expectation.competency.id, ...(effectiveDomain ? { domain: effectiveDomain } : {}), ...(filters.career_level ? { career_level: filters.career_level } : {}), ...(filters.industry ? { industry: filters.industry } : {}), limit: 100 });
      setEvidence((current) => current ? { ...current, items: response.evidence || [] } : current);
    } catch (requestError) {
      setEvidenceError(requestError);
    } finally {
      setLoadingEvidence(false);
    }
  }

  function closeEvidence() {
    setEvidence(null);
    evidenceTriggerRef.current?.focus();
  }

  useEffect(() => {
    if (!evidence) return undefined;
    closeButtonRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function closeOnEscape(event) { if (event.key === "Escape") closeEvidence(); }
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [evidence]);

  function exportReadiness() {
    const blob = new Blob([JSON.stringify({ filters, expectations: filteredExpectations }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "career-readiness.json";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  const summary = readinessSentence(filteredExpectations.length, evidenceSourceCount, selectedLevel?.name, selectedDomain?.name, selectedIndustryItem?.name);
  return <div className="career-readiness-page">
    <PageHeader eyebrow="CAREER INTELLIGENCE / READINESS" title="Career Readiness" description="A focused view of the expectations, evidence, and preparation steps for your next cybersecurity role.">
      <Badge tone="mint">Evidence on demand</Badge>
    </PageHeader>

    <section className="readiness-filter-bar" aria-labelledby="readiness-selection-heading">
      <div className="readiness-filter-heading"><div><p className="eyebrow">01 / CAREER SELECTION</p><h2 id="readiness-selection-heading">Choose your context</h2></div><div className="filter-actions"><button type="button" className="text-link" onClick={clearFilters}>Clear filters</button><button type="button" className="button button-secondary" onClick={() => setAdvancedOpen((open) => !open)} aria-expanded={advancedOpen} aria-controls="readiness-advanced-filters">{advancedOpen ? "Hide advanced" : "Advanced filters"}</button></div></div>
      <div className="readiness-filter-grid">
        <label>Security domain<select aria-label="Security Domain" value={filters.domain} onChange={(event) => updateFilter("domain", event.target.value)}><option value="">All domains</option>{roots.map((domain) => <option value={domain.slug} key={domain.id}>{domain.name}</option>)}</select></label>
        <label>Security subdomain<select aria-label="Security Subdomain" value={filters.subdomain} disabled={!subdomains.length} onChange={(event) => updateFilter("subdomain", event.target.value)}><option value="">All subdomains</option>{subdomains.map((domain) => <option value={domain.slug} key={domain.id}>{domain.name}</option>)}</select></label>
        <label>Career level<select aria-label="Career Level" value={filters.career_level} onChange={(event) => updateFilter("career_level", event.target.value)}><option value="">All levels</option>{levels.map((level) => <option value={level.slug} key={level.id}>{level.name}</option>)}</select></label>
        <label>Industry<select aria-label="Industry" value={filters.industry} onChange={(event) => updateFilter("industry", event.target.value)}><option value="">All industries</option>{industries.map((industry) => <option value={industry.slug} key={industry.id}>{industry.name}</option>)}</select></label>
      </div>
      {advancedOpen && <div id="readiness-advanced-filters" className="readiness-advanced-filters"><label>Category<select aria-label="Advanced category" value={filters.category} onChange={(event) => updateFilter("category", event.target.value)}><option value="">All categories</option>{categories.map((category) => <option value={category.slug} key={category.id}>{category.name}</option>)}</select></label><label>Importance<select aria-label="Importance" value={filters.importance} onChange={(event) => updateFilter("importance", event.target.value)}><option value="">Any priority</option><option value="essential">Essential</option><option value="important">Important</option><option value="useful">Useful</option></select></label><label>Expected proficiency<select aria-label="Expected proficiency" value={filters.proficiency} onChange={(event) => updateFilter("proficiency", event.target.value)}><option value="">Any proficiency</option>{["not_familiar", "basic", "proficient", "intermediate", "advanced", "expert"].map((value) => <option value={value} key={value}>{value.replaceAll("_", " ")}</option>)}</select></label></div>}
    </section>

    <section className="readiness-summary panel" aria-labelledby="readiness-summary-heading"><div><p className="eyebrow">02 / CAREER SUMMARY</p><h2 id="readiness-summary-heading">{selectedLevel?.name || "All career levels"} readiness in {selectedDomain?.name || "all security domains"}</h2><p className="readiness-summary-copy">{summary}</p>{summaryExpanded && <p className="readiness-summary-detail">{selectedDomain?.description || "Select a security domain to see its scope."} This view keeps detailed competency explanations and source excerpts behind expandable cards so the main path stays readable.</p>}<button type="button" className="text-link" onClick={() => setSummaryExpanded((expanded) => !expanded)} aria-expanded={summaryExpanded}>{summaryExpanded ? "Show less" : "Read more"}</button></div><div className="readiness-coverage" aria-label="Research coverage"><span>Research coverage</span><strong>{evidenceSourceCount ? `${evidenceSourceCount} source${evidenceSourceCount === 1 ? "" : "s"}` : "Limited"}</strong><small>{filteredExpectations.length} mapped expectation{filteredExpectations.length === 1 ? "" : "s"}</small></div></section>

    <section className="readiness-priorities" aria-labelledby="learning-priorities-heading"><div className="readiness-section-heading"><div><p className="eyebrow">03 / LEARNING PRIORITIES</p><h2 id="learning-priorities-heading">Start with the essentials</h2><p className="muted-copy">Inferred from expectation importance and available coverage, not source frequency alone.</p></div>{priorities.length > 6 && <button type="button" className="button button-secondary" onClick={() => setShowAllPriorities((show) => !show)}>{showAllPriorities ? "Show fewer" : `View all ${priorities.length}`}</button>}</div>{visiblePriorities.length ? <div className="priority-list">{visiblePriorities.map((expectation) => <article className="priority-item" key={expectation.competency.id}><div><h3>{expectation.competency.name}</h3><p>{expectationText(expectation)}</p></div><div className="priority-item-meta"><Badge tone={expectation.importance === "essential" ? "mint" : "blue"}>{expectation.importance || "Inferred"}</Badge><button type="button" className="text-link" onClick={() => onCompetency?.(expectation.competency.id)}>View details →</button></div></article>)}</div> : <EmptyState title="No learning priorities yet" message="Choose a broader context or remove an advanced filter." />}</section>

    <section className="readiness-explorer" aria-labelledby="competency-explorer-heading"><div className="readiness-section-heading"><div><p className="eyebrow">04 / COMPETENCY EXPLORER</p><h2 id="competency-explorer-heading">Explore one category at a time</h2></div><div className="readiness-explorer-tools"><label className="readiness-search"><span className="sr-only">Search within competencies</span><input aria-label="Search within competencies" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search competencies…" /></label><button type="button" className="text-link" onClick={() => setExpandedId(null)}>Collapse all</button></div></div><div className="readiness-category-tabs" role="tablist" aria-label="Competency categories"><button type="button" role="tab" aria-selected={!activeCategory} className={!activeCategory ? "active" : ""} onClick={() => setActiveCategory("")}>All ({filteredExpectations.length})</button>{categoriesWithData.map((category) => <button type="button" role="tab" aria-selected={activeCategory === category.slug} className={activeCategory === category.slug ? "active" : ""} key={category.slug} onClick={() => setActiveCategory(category.slug)}>{categoryLabel(category)} ({filteredExpectations.filter((expectation) => expectation.competency?.category?.slug === category.slug).length})</button>)}</div>{loading && <Loading label="Loading readiness expectations" />}{error && <ErrorState error={error} onRetry={retryLoad} />}{!loading && !error && !categoryExpectations.length && <EmptyState title="No competencies match these filters" message="Try another category, search term, or career context." />}{!loading && !error && categoryExpectations.length > 0 && <><div className="readiness-card-list">{categoryExpectations.slice(0, visibleExpectationCount).map((expectation) => <ReadinessCard key={expectation.id} expectation={expectation} expanded={expandedId === expectation.id} onToggle={() => setExpandedId((current) => current === expectation.id ? null : expectation.id)} onEvidence={openEvidence} onDetails={() => onCompetency?.(expectation.competency.id)} selectedIndustry={selectedIndustryItem?.name || "Cross-industry"} />)}</div>{visibleExpectationCount < categoryExpectations.length && <button type="button" className="button button-secondary readiness-load-more" onClick={() => setVisibleExpectationCount((count) => count + 12)}>Load more expectations ({categoryExpectations.length - visibleExpectationCount} remaining)</button>}</>}</section>

    <section className="readiness-preparation panel" aria-labelledby="preparation-heading"><div><p className="eyebrow">05 / PREPARATION AND ASSESSMENT</p><h2 id="preparation-heading">Turn expectations into a plan</h2><p className="muted-copy">Keep assessment, recommendations, comparison, and export actions together instead of repeating them on every card.</p></div><div className="preparation-actions"><button type="button" className="button" onClick={() => onNavigate?.("competency-gaps")}>Self-assess skills <span>→</span></button><button type="button" className="button button-secondary" onClick={() => onNavigate?.("career-roadmap")}>Recommendations & exercises <span>→</span></button><button type="button" className="button button-secondary" onClick={() => onNavigate?.("compare")}>Compare career levels <span>→</span></button><button type="button" className="button button-secondary" onClick={exportReadiness}>Export current view <span>↓</span></button></div></section>

    {evidence && <EvidenceDrawer evidence={evidence} loading={loadingEvidence} error={evidenceError} closeButtonRef={closeButtonRef} onClose={closeEvidence} selectedIndustry={selectedIndustryItem?.name || "Cross-industry"} />}
    <button type="button" className="back-to-top" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>↑ <span>Back to top</span></button>
  </div>;
}

function ReadinessCard({ expectation, expanded, onToggle, onEvidence, onDetails, selectedIndustry }) {
  const fields = [["What you need to know", expectation.technical_knowledge], ["What you should be able to do", expectation.practical_capability], ["Practical demonstration", expectation.expectation_description], ["Tools and technologies", expectation.tools_technologies], ["Qualifications", expectation.qualifications], ["Responsibility and scope", expectation.responsibility_type], ["Industry-specific context", expectation.industry?.name || selectedIndustry], ["Experience expectations", expectation.experience_years_min !== null || expectation.experience_years_max !== null ? `${expectation.experience_years_min ?? 0}${expectation.experience_years_max !== null ? `–${expectation.experience_years_max}` : "+"} years` : ""]].filter(([, value]) => clean(value));
  return <article className={`readiness-card ${expanded ? "expanded" : ""}`}><div className="readiness-card-summary"><div className="readiness-card-title"><h3>{expectation.competency.name}</h3><p>{expectationText(expectation)}</p></div><div className="readiness-card-meta"><Badge tone="violet">{expectation.proficiency_level}</Badge><span>{sourceCount(expectation)} evidence</span><button type="button" className="card-expand" onClick={onToggle} aria-expanded={expanded} aria-controls={`expectation-detail-${expectation.id}`}>{expanded ? "Collapse" : "Expand"}<span aria-hidden="true">{expanded ? "⌃" : "⌄"}</span></button></div></div>{expanded && <div id={`expectation-detail-${expectation.id}`} className="readiness-card-detail"><div className="readiness-detail-grid">{fields.map(([label, value]) => <div key={label}><span>{label}</span><p>{value}</p></div>)}</div><div className="readiness-card-actions"><button type="button" className="text-link" onClick={(event) => onEvidence(expectation, event.currentTarget)}>View supporting evidence ({sourceCount(expectation)})</button><button type="button" className="text-link" onClick={onDetails}>Open competency details →</button></div></div>}</article>;
}

function EvidenceDrawer({ evidence, loading, error, closeButtonRef, onClose, selectedIndustry }) {
  const expectation = evidence.expectation;
  const items = evidence.items || [];
  return <div className="evidence-drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><aside className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="evidence-drawer-title"><div className="evidence-drawer-header"><div><p className="eyebrow">SUPPORTING RESEARCH</p><h2 id="evidence-drawer-title">{expectation.competency.name}</h2><p className="muted-copy">{expectation.career_level?.name || "Selected level"} · {expectation.industry?.name || selectedIndustry}</p></div><button ref={closeButtonRef} type="button" className="drawer-close" aria-label="Close evidence drawer" onClick={onClose}>×</button></div><div className="evidence-drawer-content">{loading && <Loading label="Loading published evidence" />}{error && <ErrorState error={error} />}{!loading && !error && !items.length && <EmptyState title="No supporting evidence" message="This expectation is retained without a published source excerpt." />}{!loading && !error && items.map((item, index) => <article className="evidence-drawer-item" key={`${item.source_id || item.source_url}-${index}`}><div className="evidence-drawer-source"><h3>{item.source_title}</h3><a href={item.source_url} target="_blank" rel="noreferrer">Open source ↗</a></div><dl><div><dt>Research date</dt><dd>{formatDate(item.research_date)}</dd></div><div><dt>Industry</dt><dd>{expectation.industry?.name || selectedIndustry}</dd></div><div><dt>Career level</dt><dd>{expectation.career_level?.name || "Selected level"}</dd></div><div><dt>Publication version</dt><dd>{item.publication_version || "Current published version"}</dd></div></dl><blockquote>{item.excerpt || "No excerpt was retained for this source."}</blockquote></article>)}</div></aside></div>;
}
