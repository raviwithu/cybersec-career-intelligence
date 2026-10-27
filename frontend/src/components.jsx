export function Loading({ label = "Loading intelligence" }) {
  return <div className="loading-state" role="status"><span className="spinner" />{label}</div>;
}

export function ErrorState({ error, onRetry }) {
  return <div className="empty-state error-state" role="alert"><span className="state-icon">!</span><div><strong>Unable to load this view</strong><p>{error?.message || "The API did not return a usable response."}</p>{onRetry && <button className="button button-secondary" onClick={onRetry}>Try again</button>}</div></div>;
}

export function EmptyState({ title = "No data yet", message = "There are no records matching this view." }) {
  return <div className="empty-state"><span className="state-icon">◌</span><div><strong>{title}</strong><p>{message}</p></div></div>;
}

export function Badge({ children, tone = "neutral" }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function StatCard({ label, value, detail, accent = "mint" }) {
  return <article className={`stat-card stat-${accent}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>;
}

export function PageHeader({ eyebrow, title, description, children }) {
  return <div className="page-header"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="page-description">{description}</p></div>{children && <div className="page-header-actions">{children}</div>}</div>;
}

export function DomainTree({ domains, selectedSlug, onSelect, counts = {} }) {
  return <nav className="domain-tree" aria-label="Security domains">
    {domains.map((domain) => <div key={domain.id}>
      <button className={`domain-tree-item ${selectedSlug === domain.slug ? "selected" : ""}`} onClick={() => onSelect(domain)}>
        <span className="tree-marker">{domain.children?.length ? "⌄" : "·"}</span><span>{domain.name}</span><small>{counts[domain.id]?.expectations || 0}</small>
      </button>
      {domain.children?.length > 0 && <div className="domain-children">{domain.children.map((child) => <button key={child.id} className={`domain-tree-item child ${selectedSlug === child.slug ? "selected" : ""}`} onClick={() => onSelect(child)}><span className="tree-marker">↳</span><span>{child.name}</span><small>{counts[child.id]?.expectations || 0}</small></button>)}</div>}
    </div>)}
  </nav>;
}

export function ExpectationCard({ expectation, onCompetency }) {
  return <article className="expectation-card">
    <div className="card-topline"><Badge tone={expectation.importance === "essential" ? "mint" : "blue"}>{expectation.importance}</Badge><Badge>{expectation.proficiency_level}</Badge><span className="card-domain">{expectation.responsibility_type}</span></div>
    <button className="text-link competency-link" onClick={() => onCompetency?.(expectation.competency.id)}>{expectation.competency.name}</button>
    <p>{expectation.expectation_description}</p>
    {(expectation.experience_years_min !== null || expectation.experience_years_max !== null) && <div className="experience-line"><span>Experience</span><strong>{expectation.experience_years_min ?? 0}{expectation.experience_years_max !== null ? `–${expectation.experience_years_max}` : "+"} years</strong></div>}
    {expectation.supporting_sources?.length > 0 && <SourceList sources={expectation.supporting_sources} compact />}
  </article>;
}

export function SourceList({ sources = [], compact = false }) {
  if (!sources.length) return null;
  return <div className={`source-list ${compact ? "compact" : ""}`}><span className="source-label">Research evidence</span>{sources.map(({ source, supporting_excerpt }) => <a className="source-item" href={source.source_url} target="_blank" rel="noreferrer" key={`${source.id}-${supporting_excerpt}`}><span>{source.source_title}</span><small>{supporting_excerpt || source.source_type}</small></a>)}</div>;
}

export function LevelChips({ levels, selected, onSelect }) {
  return <div className="level-chips" role="group" aria-label="Career level"><button className={!selected ? "active" : ""} onClick={() => onSelect?.(null)}>All levels</button>{levels.map((level) => <button key={level.id} className={selected === level.slug ? "active" : ""} onClick={() => onSelect?.(level.slug)}>{level.name}</button>)}</div>;
}
