import { useMemo, useState } from "react";

import { fetchComparison, fetchCompetencies, fetchCompetency, fetchExpectation, fetchExpectations, fetchSearch } from "./api";
import { Badge, EmptyState, ErrorState, ExpectationCard, LevelChips, Loading, PageHeader, SourceList, StatCard } from "./components";
import { useApi } from "./useApi";

function domainCounts(matrix, domains) {
  const direct = Object.fromEntries((matrix?.domains || []).map(({ domain, cells }) => [domain.id, {
    expectations: cells.reduce((sum, cell) => sum + cell.expectation_count, 0),
    competencies: cells.reduce((sum, cell) => sum + cell.competency_count, 0),
  }]));
  const totals = {};
  function aggregate(domain) {
    const own = direct[domain.id] || { expectations: 0, competencies: 0 };
    const descendants = (domain.children || []).map(aggregate);
    const total = descendants.reduce((sum, child) => ({ expectations: sum.expectations + child.expectations, competencies: sum.competencies + child.competencies }), own);
    totals[domain.id] = total;
    return total;
  }
  domains.forEach(aggregate);
  return totals;
}

function coverageCount(matrix, levelId) {
  return (matrix?.domains || []).reduce((sum, item) => sum + (item.cells.find((cell) => cell.career_level_id === levelId)?.expectation_count || 0), 0);
}

export function DashboardPage({ domains, levels, matrix, competencyTotal, expectationTotal, onNavigate }) {
  const subdomainCount = domains.reduce((sum, domain) => sum + (domain.children?.length || 0), 0);
  const coveredLevels = levels.filter((level) => coverageCount(matrix, level.id) > 0).length;
  return <>
    <PageHeader eyebrow="KNOWLEDGE BASE / OVERVIEW" title="Cybersecurity career intelligence" description="A consolidated view of what security practitioners are expected to know, do, and demonstrate across domains and career levels."><Badge tone="mint">Illustrative seed data clearly labeled</Badge></PageHeader>
    <section className="stats-grid">
      <StatCard label="Security domains" value={domains.length} detail="Core research areas" />
      <StatCard label="Embedded subdomains" value={subdomainCount} detail="Nested focus areas" accent="blue" />
      <StatCard label="Competencies" value={competencyTotal} detail="Reusable knowledge units" accent="violet" />
      <StatCard label="Expectations" value={expectationTotal} detail="Consolidated records" accent="amber" />
      <StatCard label="Career coverage" value={`${coveredLevels}/${levels.length}`} detail="Levels with current data" accent="rose" />
    </section>
    <section className="dashboard-grid">
      <article className="feature-card feature-card-wide"><div className="feature-icon">⌘</div><div><p className="eyebrow">START WITH A DOMAIN</p><h2>Explore the security landscape</h2><p>Move from a domain overview into the expectations that define technical and leadership growth at each level.</p><button className="button" onClick={() => onNavigate("domains")}>Open Domain Explorer <span>→</span></button></div></article>
      <article className="feature-card"><div className="feature-icon blue-icon">▦</div><p className="eyebrow">COMPARE COVERAGE</p><h2>Career matrix</h2><p>See where expectations cluster across all security domains and career tracks.</p><button className="button button-secondary" onClick={() => onNavigate("matrix")}>View matrix <span>→</span></button></article>
      <article className="evidence-card"><div><p className="eyebrow">RESEARCH NOTE</p><h2>How to read this knowledge base</h2><p>Expectations are organized by domain, career level, competency category, proficiency, importance, and responsibility type. Illustrative development records are labeled; they are not market research.</p></div><div className="evidence-line"><span className="pulse" /> Evidence links appear on individual expectations when available.</div></article>
    </section>
  </>;
}

export function DomainsPage({ domains, levels, categories, matrix, selectedDomain, selectedLevel, onSelectDomain, onSelectLevel, onCompetency }) {
  const [activeCategory, setActiveCategory] = useState("all");
  const counts = useMemo(() => domainCounts(matrix, domains), [matrix, domains]);
  const domainSlug = selectedDomain?.slug;
  const { data, loading, error, reload } = useApi(
    () => selectedDomain ? Promise.all([
      fetchExpectations({ domain: domainSlug, ...(selectedLevel ? { level: selectedLevel } : {}), page_size: 100 }),
      fetchCompetencies({ domain: domainSlug, ...(selectedLevel ? { level: selectedLevel } : {}), page_size: 100 }),
    ]).then(([expectations, competencies]) => ({ expectations, competencies })) : Promise.resolve(null),
    [domainSlug, selectedLevel],
    { immediate: Boolean(selectedDomain) },
  );
  const expectations = data?.expectations?.items || [];
  const grouped = expectations.reduce((groups, item) => {
    const key = item.competency.category.slug;
    groups[key] ||= [];
    groups[key].push(item);
    return groups;
  }, {});
  const categoriesWithData = categories.filter((category) => grouped[category.slug]?.length);
  return <>
    <PageHeader eyebrow="DOMAIN EXPLORER" title="Understand the work by domain" description="Select a security domain, then narrow the view to a career level. Every count and expectation below comes from the knowledge-base APIs."><Badge>{selectedDomain?.name || "Choose a domain"}</Badge></PageHeader>
    <div className="explorer-layout">
      <aside className="panel domain-panel"><div className="panel-title-row"><div><p className="eyebrow">SECURITY TAXONOMY</p><h2>Domains</h2></div><span className="muted-label">{domains.length} roots</span></div><div className="domain-list-wrapper"><div className="domain-tree-scroll"><nav className="domain-tree" aria-label="Security domains">{domains.map((domain) => <div key={domain.id}><button className={`domain-tree-item ${selectedDomain?.slug === domain.slug ? "selected" : ""}`} onClick={() => onSelectDomain(domain)}><span className="tree-marker">{domain.children?.length ? "⌄" : "·"}</span><span>{domain.name}</span><small>{counts[domain.id]?.expectations || 0}</small></button>{domain.children?.map((child) => <button key={child.id} className={`domain-tree-item child ${selectedDomain?.slug === child.slug ? "selected" : ""}`} onClick={() => onSelectDomain(child)}><span className="tree-marker">↳</span><span>{child.name}</span><small>{counts[child.id]?.expectations || 0}</small></button>)}</div>)}</nav></div></div></aside>
      <section className="domain-content">
        {!selectedDomain && <EmptyState title="Select a security domain" message="Choose a root domain or embedded subdomain to inspect its expectations." />}
        {selectedDomain && <>
          <article className="domain-intro"><div><div className="card-topline"><Badge tone="blue">{selectedDomain.parent_id ? "Subdomain" : "Security domain"}</Badge><span className="mono-label">ORDER {String(selectedDomain.display_order).padStart(2, "0")}</span></div><h2>{selectedDomain.name}</h2><p>{selectedDomain.description}</p></div><div className="domain-mini-stats"><strong>{counts[selectedDomain.id]?.competencies || data?.competencies?.meta?.total || 0}</strong><span>competencies</span><strong>{counts[selectedDomain.id]?.expectations || data?.expectations?.meta?.total || 0}</strong><span>expectations</span></div></article>
          <div className="filter-bar"><div><span className="filter-label">CAREER LEVEL</span><LevelChips levels={levels} selected={selectedLevel} onSelect={onSelectLevel} /></div><div><span className="filter-label">CATEGORY</span><select aria-label="Expectation category" value={activeCategory} onChange={(event) => setActiveCategory(event.target.value)}><option value="all">All categories</option>{categories.map((category) => <option value={category.slug} key={category.slug}>{category.name}</option>)}</select></div></div>
          {loading && <Loading label="Loading expectations" />}
          {error && <ErrorState error={error} onRetry={reload} />}
          {!loading && !error && expectations.length === 0 && <EmptyState title="No expectations in this view" message="Try a different career level or category." />}
          {!loading && !error && expectations.length > 0 && <div className="category-sections">{categoriesWithData.filter((category) => activeCategory === "all" || activeCategory === category.slug).map((category, index) => <section className="category-section" key={category.slug}><div className="category-heading"><div><span className="category-kicker">{String(index + 1).padStart(2, "0")}</span><h3>{category.name}</h3></div><span>{grouped[category.slug]?.length || 0} expectations</span></div><div className="expectation-grid">{(grouped[category.slug] || []).map((expectation) => <ExpectationCard key={expectation.id} expectation={expectation} onCompetency={onCompetency} />)}</div></section>)}</div>}
        </>}
      </section>
    </div>
  </>;
}

export function MatrixPage({ matrix, domains, levels, onCell }) {
  return <><PageHeader eyebrow="CAREER MATRIX" title="See the coverage at a glance" description="Each cell reports the number of consolidated expectations currently available for a domain and career level. Select a cell to open its domain view." /><div className="track-legend"><span><i className="track-dot technical" />Technical track</span><span><i className="track-dot management" />Management track</span><span><i className="track-dot shared" />Shared track</span></div><div className="matrix-wrap panel"><div className="matrix-scroll"><table className="career-matrix"><thead><tr><th>Security domain</th>{levels.map((level) => <th key={level.id}><span className={`level-track ${level.career_track}`}>{level.career_track}</span>{level.name}</th>)}</tr></thead><tbody>{(matrix?.domains || []).map(({ domain, cells }) => <tr key={domain.id}><th><span className="matrix-domain-name">{domain.parent_id ? "↳ " : ""}{domain.name}</span><small>{domain.slug}</small></th>{levels.map((level) => { const cell = cells.find((item) => item.career_level_id === level.id); return <td key={level.id}><button className={`matrix-cell ${cell?.expectation_count ? "has-data" : ""}`} onClick={() => onCell(domain, level)} aria-label={`${domain.name}, ${level.name}: ${cell?.expectation_count || 0} expectations`}><strong>{cell?.expectation_count || 0}</strong><small>{cell?.competency_count || 0} competencies</small></button></td>; })}</tr>)}</tbody></table></div></div></>;
}

function ComparisonGroup({ title, items, levelName, onCompetency }) {
  return <section className="comparison-section"><div className="section-title-row"><h2>{title}</h2><Badge>{items.length}</Badge></div>{items.length === 0 ? <EmptyState title={`No ${title.toLowerCase()} found`} message="The API returned no records for this comparison." /> : <div className="comparison-grid">{items.map((item) => <article className="comparison-card" key={item.competency.id}><button className="text-link" onClick={() => onCompetency(item.competency.id)}>{item.competency.name}</button><Badge tone="violet">{item.competency.category.name}</Badge><p>{item.competency.description}</p>{levelName && item.expectations_by_level[levelName]?.map((expectation) => <div className="difference-line" key={expectation.id}><strong>{expectation.proficiency_level}</strong><span>{expectation.expectation_description}</span></div>)}</article>)}</div>}</section>;
}

export function ComparePage({ domains, levels, selectedDomain, compareLevels, onDomainChange, onLevelsChange, onCompetency }) {
  const canCompare = selectedDomain && compareLevels.length === 2 && compareLevels[0] !== compareLevels[1];
  const { data, loading, error, reload } = useApi(() => fetchComparison(selectedDomain?.slug, compareLevels), [selectedDomain?.slug, ...compareLevels], { immediate: canCompare });
  const levelNames = data?.levels?.map((item) => item.level.slug) || compareLevels;
  return <><PageHeader eyebrow="CAREER COMPARISON" title="Make progression visible" description="Compare the expectations that change as responsibility, proficiency, and technical depth increase within one domain." />
    <div className="compare-controls panel"><label>Security domain<select value={selectedDomain?.slug || ""} onChange={(event) => onDomainChange(domains.find((domain) => domain.slug === event.target.value))}>{domains.map((domain) => <option value={domain.slug} key={domain.id}>{domain.name}</option>)}</select></label><div><span className="filter-label">Compare levels</span><div className="compare-selects"><select value={compareLevels[0] || ""} onChange={(event) => onLevelsChange([event.target.value, compareLevels[1]])}>{levels.map((level) => <option value={level.slug} key={level.id}>{level.name}</option>)}</select><span>vs</span><select value={compareLevels[1] || ""} onChange={(event) => onLevelsChange([compareLevels[0], event.target.value])}>{levels.map((level) => <option value={level.slug} key={level.id}>{level.name}</option>)}</select></div></div></div>
    {!canCompare && <EmptyState title="Choose two distinct career levels" message="Select a domain and two levels to generate a live comparison." />}
    {loading && <Loading label="Building comparison" />}{error && <ErrorState error={error} onRetry={reload} />}{data && !loading && !error && <div className="comparison-content"><div className="comparison-summary"><div><p className="eyebrow">{data.domain.name}</p><h2>{data.levels.map((item) => item.level.name).join(" vs ")}</h2></div><div className="summary-levels">{data.levels.map((item) => <div key={item.level.id}><strong>{item.competency_count}</strong><span>{item.level.name} competencies</span></div>)}</div></div><ComparisonGroup title="Shared competencies" items={data.shared_competencies} onCompetency={onCompetency} /><section className="comparison-section"><div className="section-title-row"><h2>Unique to each level</h2></div><div className="unique-columns">{data.levels.map((level) => <div key={level.level.slug}><h3>{level.level.name}</h3><ComparisonGroup title="" items={data.unique_competencies[level.level.slug] || []} onCompetency={onCompetency} /></div>)}</div></section><ComparisonGroup title="Where expectations differ" items={data.differences} onCompetency={onCompetency} /></div>}
  </>;
}

export function CompetenciesPage({ domains, levels, categories, selectedCompetencyId, onSelectCompetency }) {
  const [filters, setFilters] = useState({ search: "", domain: "", level: "", category: "" });
  const params = { page: 1, page_size: 100, ...filters };
  const { data, loading, error, reload } = useApi(() => fetchCompetencies(params), [filters.search, filters.domain, filters.level, filters.category]);
  const detailState = useApi(() => selectedCompetencyId ? fetchCompetency(selectedCompetencyId) : Promise.resolve(null), [selectedCompetencyId], { immediate: Boolean(selectedCompetencyId) });
  const expectationIds = detailState.data?.expectations?.map((expectation) => expectation.id).join(",") || "";
  const expectationDetails = useApi(() => expectationIds ? Promise.all(detailState.data.expectations.map((expectation) => fetchExpectation(expectation.id))) : Promise.resolve([]), [expectationIds], { immediate: Boolean(expectationIds) });
  function update(key, value) { setFilters((current) => ({ ...current, [key]: value })); }
  return <><PageHeader eyebrow="COMPETENCY EXPLORER" title="Browse the building blocks" description="Search reusable competencies and inspect where they appear across the taxonomy and career ladder." />
    <div className="filter-bar competency-filters"><label>Search competencies<input value={filters.search} onChange={(event) => update("search", event.target.value)} placeholder="Try secure boot, incident response…" /></label><label>Domain<select value={filters.domain} onChange={(event) => update("domain", event.target.value)}><option value="">All domains</option>{domains.flatMap((domain) => [domain, ...(domain.children || [])]).map((domain) => <option value={domain.slug} key={domain.id}>{domain.name}</option>)}</select></label><label>Level<select value={filters.level} onChange={(event) => update("level", event.target.value)}><option value="">All levels</option>{levels.map((level) => <option value={level.slug} key={level.id}>{level.name}</option>)}</select></label><label>Category<select value={filters.category} onChange={(event) => update("category", event.target.value)}><option value="">All categories</option>{categories.map((category) => <option value={category.slug} key={category.id}>{category.name}</option>)}</select></label></div>
    {loading && <Loading label="Searching competencies" />}{error && <ErrorState error={error} onRetry={reload} />}{!loading && !error && <div className="competency-layout"><section><div className="result-heading"><span>{data?.meta?.total || 0} competencies</span></div>{data?.items?.length ? <div className="competency-list">{data.items.map((item) => <button className={`competency-row ${selectedCompetencyId === item.id ? "selected" : ""}`} key={item.id} onClick={() => onSelectCompetency(item.id)}><div><strong>{item.name}</strong><p>{item.description}</p></div><div className="competency-meta"><Badge tone="violet">{item.category.name}</Badge><small>{item.domains.length} domains · {item.career_levels.length} levels</small></div></button>)}</div> : <EmptyState title="No competencies found" message="Try removing a filter or searching for a different term." />}</section><aside className="panel detail-panel">{detailState.loading && <Loading label="Loading competency" />}{detailState.error && <ErrorState error={detailState.error} onRetry={detailState.reload} />}{!selectedCompetencyId && !detailState.loading && <EmptyState title="Select a competency" message="Choose a result to see its expectations and relationships." />}{detailState.data && <CompetencyDetail detail={detailState.data} expectationDetails={expectationDetails.data || []} />}</aside></div>}
  </>;
}

function CompetencyDetail({ detail, expectationDetails }) {
  return <div className="detail-content"><div className="card-topline"><Badge tone="violet">{detail.category.name}</Badge><span className="mono-label">{detail.slug}</span></div><h2>{detail.name}</h2><p>{detail.description}</p><div className="detail-block"><span className="filter-label">ASSOCIATED DOMAINS</span><div className="tag-list">{detail.domains.map((domain) => <Badge key={domain.id} tone="blue">{domain.name}</Badge>)}</div></div><div className="detail-block"><span className="filter-label">CAREER LEVELS</span><div className="tag-list">{detail.career_levels.map((level) => <Badge key={level.id}>{level.name}</Badge>)}</div></div><div className="detail-block"><span className="filter-label">RELATED COMPETENCIES</span>{detail.related_competencies.length ? detail.related_competencies.map((relation) => <div className="related-row" key={relation.id}><span>{relation.competency_name}</span><Badge>{relation.relationship_type}</Badge></div>) : <p className="muted-copy">No related competencies have been recorded.</p>}</div><div className="detail-block"><span className="filter-label">EXPECTATIONS</span>{detail.expectations.map((expectation) => { const fullExpectation = expectationDetails.find((item) => item.id === expectation.id); return <div className="mini-expectation" key={expectation.id}><div><strong>{expectation.career_level.name}</strong><Badge tone="mint">{expectation.proficiency_level}</Badge></div><p>{expectation.expectation_description}</p><span>{expectation.responsibility_type} · {expectation.domain.name}</span>{fullExpectation?.supporting_sources?.length > 0 && <SourceList sources={fullExpectation.supporting_sources} compact />}</div>; })}</div></div>;
}

export function SearchPage({ domains, levels, onCompetency, onDomain }) {
  const [keyword, setKeyword] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [domain, setDomain] = useState("");
  const [level, setLevel] = useState("");
  const { data, loading, error, reload } = useApi(() => fetchSearch({ keyword: submitted, domain, level, page: 1, page_size: 50 }), [submitted, domain, level], { immediate: Boolean(submitted) });
  function submit(event) { event.preventDefault(); setSubmitted(keyword.trim()); }
  return <><PageHeader eyebrow="GLOBAL SEARCH" title="Find a signal across the knowledge base" description="Search domains, reusable competencies, and consolidated expectations. Results are returned by the FastAPI search endpoint." /><form className="search-form" onSubmit={submit}><input aria-label="Global search" value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="Search secure boot, risk management, architecture…" /><button className="button" type="submit" aria-label="Submit search">Search <span>⌕</span></button></form><div className="search-filters"><select aria-label="Search domain" value={domain} onChange={(event) => setDomain(event.target.value)}><option value="">All domains</option>{domains.flatMap((item) => [item, ...(item.children || [])]).map((item) => <option key={item.id} value={item.slug}>{item.name}</option>)}</select><select aria-label="Search level" value={level} onChange={(event) => setLevel(event.target.value)}><option value="">All levels</option>{levels.map((item) => <option key={item.id} value={item.slug}>{item.name}</option>)}</select></div>{submitted && loading && <Loading label="Searching the knowledge base" />}{submitted && error && <ErrorState error={error} onRetry={reload} />}{submitted && !loading && !error && <section className="search-results"><div className="result-heading"><span>{data?.meta?.total || 0} results for <strong>“{submitted}”</strong></span></div>{data?.items?.length ? data.items.map((result) => <button className="search-result" key={`${result.result_type}-${result.id}`} onClick={() => result.result_type === "competency" ? onCompetency(result.competency_id || result.id) : result.domain ? onDomain(result.domain.slug) : null}><div className="result-type">{result.result_type}</div><div><strong>{result.name}</strong><p>{result.description}</p><span>{result.domain?.name || "Knowledge base"}{result.career_level ? ` · ${result.career_level.name}` : ""}</span></div><span className="result-arrow">→</span></button>) : <EmptyState title="No matching records" message="Try a broader keyword or remove a filter." />}</section>}{!submitted && <EmptyState title="Search when you are ready" message="Use the search field to explore domains, competencies, and expectations." />}</>;
}
