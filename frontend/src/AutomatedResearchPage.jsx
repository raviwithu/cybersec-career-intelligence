import { useEffect, useState } from "react";

import {
  configureAutomatedResearchSchedule,
  createAutomatedResearchSource,
  disableAutomatedResearchSource,
  fetchAutomatedResearchCoverage,
  fetchAutomatedResearchDashboard,
  fetchAutomatedResearchSources,
  fetchAutomatedResearchRuns,
  getAdminSessionKey,
  pauseAutomatedResearchSchedule,
  resumeAutomatedResearchSchedule,
  setAdminSessionKey,
  clearAdminSessionKey,
  startAutomatedResearchRun,
} from "./api";
import { Badge, EmptyState, ErrorState, Loading, PageHeader, StatCard } from "./components";
import LinkedInJobSearchPanel from "./LinkedInJobSearchPanel";

const emptyForm = { name: "", source_type: "rss", endpoint_url: "", collection_frequency: "manual", interval_minutes: 1440, urls: "" };

function formatDate(value) { return value ? new Date(value).toLocaleString() : "Not yet"; }
function statusTone(value) { return value === "success" || value === "completed" || value === "analyzed" ? "mint" : value === "failed" || value === "completed_with_errors" ? "rose" : "amber"; }

function SourceForm({ onCreated, adminKey }) {
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const configuration = form.source_type === "url_collection" ? { urls: form.urls.split("\n").map((url) => url.trim()).filter(Boolean) } : {};
      await createAutomatedResearchSource({ name: form.name.trim(), source_type: form.source_type, endpoint_url: form.endpoint_url.trim(), collection_frequency: form.collection_frequency, interval_minutes: Number(form.interval_minutes), configuration }, adminKey);
      setForm(emptyForm); await onCreated();
    } catch (requestError) { setError(requestError); } finally { setBusy(false); }
  }
  return <form className="automation-form" onSubmit={submit}><p className="eyebrow">APPROVE A RESEARCH ENDPOINT</p><div className="automation-form-grid"><label>Source name<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="CISA advisories" /></label><label>Source type<select value={form.source_type} onChange={(event) => setForm({ ...form, source_type: event.target.value })}><option value="public_api">Public API</option><option value="html">Permitted HTML page</option><option value="rss">RSS / Atom feed</option><option value="url_collection">Administrator URL collection</option></select></label><label className="automation-wide">Base URL or API endpoint<input required type="url" value={form.endpoint_url} onChange={(event) => setForm({ ...form, endpoint_url: event.target.value })} placeholder="https://example.org/research" /></label><label>Schedule<select value={form.collection_frequency} onChange={(event) => setForm({ ...form, collection_frequency: event.target.value })}><option value="manual">Manual only</option><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="interval">Custom interval</option></select></label>{form.collection_frequency === "interval" && <label>Interval minutes<input type="number" min="5" max="10080" value={form.interval_minutes} onChange={(event) => setForm({ ...form, interval_minutes: event.target.value })} /></label>}{form.source_type === "url_collection" && <label className="automation-wide">Approved URLs <span className="hint">one per line</span><textarea required rows="3" value={form.urls} onChange={(event) => setForm({ ...form, urls: event.target.value })} /></label>}</div>{error && <ErrorState error={error} />}<button className="button" disabled={busy}>{busy ? "Registering…" : "Register approved source"}</button></form>;
}

function SourceRows({ sources, adminKey, onChanged }) {
  async function action(source, kind) {
    if (kind === "disable" && !window.confirm(`Disable ${source.name}? Existing provenance remains available.`)) return;
    if (kind === "disable") await disableAutomatedResearchSource(source.id, adminKey);
    if (kind === "pause") await pauseAutomatedResearchSchedule(source.id, adminKey);
    if (kind === "resume") await resumeAutomatedResearchSchedule(source.id, adminKey);
    await onChanged();
  }
  if (!sources.length) return <EmptyState title="No approved sources" message="Register a public API, permitted page, feed, or administrator URL collection to begin." />;
  return <div className="automation-source-list">{sources.map((source) => <article className="automation-source-row" key={source.id}><div><div className="automation-row-title"><strong>{source.name}</strong><Badge tone={statusTone(source.collection_status)}>{source.collection_status}</Badge><Badge>{source.source_type.replaceAll("_", " ")}</Badge></div><span>{source.endpoint_url}</span><small>Last success {formatDate(source.last_successful_collection)} · Next run {formatDate(source.next_run_at)}</small>{source.last_error && <small className="error-copy">{source.last_error}</small>}</div><div className="automation-row-actions">{source.schedule?.paused ? <button className="button button-secondary" onClick={() => action(source, "resume")}>Resume</button> : source.schedule?.enabled && <button className="button button-secondary" onClick={() => action(source, "pause")}>Pause</button>}<button className="button button-danger" onClick={() => action(source, "disable")}>Disable</button></div></article>)}</div>;
}

function CoverageTable({ coverage }) {
  if (!coverage?.cells?.length) return <EmptyState title="No taxonomy coverage" message="Seeded industries, domains, and career levels will appear here." />;
  return <div className="table-wrap automation-coverage-table"><table><thead><tr><th>Industry</th><th>Security domain</th><th>Career level</th><th>Evidence</th><th>Sources</th><th>Coverage</th></tr></thead><tbody>{coverage.cells.map((cell) => <tr key={`${cell.industry.id}-${cell.domain.id}-${cell.career_level.id}`}><td>{cell.industry.name}</td><td>{cell.domain.name}</td><td>{cell.career_level.name}</td><td>{cell.evidence_count}</td><td>{cell.source_count}</td><td><Badge tone={cell.label === "adequate" ? "mint" : cell.label === "limited" ? "amber" : "rose"}>{cell.label}</Badge></td></tr>)}</tbody></table></div>;
}

export default function AutomatedResearchPage({ onOpenReview }) {
  const [enteredKey, setEnteredKey] = useState(() => getAdminSessionKey());
  const [adminKey, setAdminKey] = useState(() => getAdminSessionKey());
  const [dashboard, setDashboard] = useState(null);
  const [sources, setSources] = useState([]);
  const [runs, setRuns] = useState([]);
  const [coverage, setCoverage] = useState(null);
  const [tab, setTab] = useState("overview");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function load() {
    if (!adminKey) return;
    setLoading(true); setError(null);
    try { const [nextDashboard, nextSources, nextRuns, nextCoverage] = await Promise.all([fetchAutomatedResearchDashboard(adminKey), fetchAutomatedResearchSources(adminKey), fetchAutomatedResearchRuns(adminKey), fetchAutomatedResearchCoverage(adminKey)]); setDashboard(nextDashboard); setSources(nextSources); setRuns(nextRuns); setCoverage(nextCoverage); } catch (requestError) { setError(requestError); } finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [adminKey]);
  async function startRun() { setBusy(true); setError(null); try { await startAutomatedResearchRun({ source_ids: null }, adminKey); await load(); setTab("runs"); } catch (requestError) { setError(requestError); } finally { setBusy(false); } }
  async function updateSource(sourceId, payload) { setBusy(true); try { await configureAutomatedResearchSchedule(sourceId, payload, adminKey); await load(); } catch (requestError) { setError(requestError); } finally { setBusy(false); } }

  if (!adminKey) return <><PageHeader eyebrow="PHASE 6 / AUTOMATED RESEARCH" title="Automated Research" description="Collect approved cybersecurity research sources, analyze evidence, and propose knowledge-base changes for review." /><section className="panel research-auth"><p className="eyebrow">ADMINISTRATOR ACCESS</p><h2>Unlock automated research</h2><p className="muted-copy">Only the administrator can configure endpoints, schedules, collection runs, and proposed changes.</p><input aria-label="Administrator API key" type="password" value={enteredKey} onChange={(event) => setEnteredKey(event.target.value)} placeholder="X-Admin-API-Key" /><button className="button" disabled={!enteredKey} onClick={() => { setAdminSessionKey(enteredKey); setAdminKey(enteredKey); }}>Open automation workspace</button></section></>;

  const overview = dashboard?.overview || {};
  const stats = [["Active sources", overview.active_research_sources ?? 0, "Approved endpoints", "mint"], ["Last run", formatDate(overview.last_research_run), "Execution history", "blue"], ["Awaiting review", overview.new_findings_awaiting_review ?? 0, "Existing Research Review queue", "amber"], ["Duplicates skipped", overview.duplicate_sources_skipped ?? 0, "Unchanged content", "violet"]];
  return <><PageHeader eyebrow="PHASE 6 / AUTOMATED RESEARCH" title="Automated Research" description="Collect approved cybersecurity research, classify findings across domain, career level, and industry, and prepare auditable review proposals."><div className="review-card-actions"><button className="button" disabled={busy} onClick={startRun}>Start research run</button><button className="button button-secondary" onClick={() => { clearAdminSessionKey(); setAdminKey(""); setEnteredKey(""); }}>Lock workspace</button></div></PageHeader>{error && <ErrorState error={error} onRetry={load} />}{loading && !dashboard ? <section className="panel"><Loading label="Loading research automation" /></section> : <><section className="stats-grid automation-stats">{stats.map(([label, value, detail, accent]) => <StatCard key={label} label={label} value={value} detail={detail} accent={accent} />)}</section><div className="automation-tabs" role="tablist">{[["overview", "Overview"], ["sources", "Research sources"], ["job-search", "LinkedIn Job Search"], ["runs", "Research runs"], ["coverage", "Research coverage"]].map(([id, label]) => <button className={tab === id ? "active" : ""} role="tab" aria-selected={tab === id} key={id} onClick={() => setTab(id)}>{label}</button>)}</div>{tab === "overview" && <div className="automation-dashboard-grid"><section className="panel"><div className="panel-title-row"><div><p className="eyebrow">PIPELINE HEALTH</p><h2>Collection and analysis</h2></div><Badge tone={overview.failed_collections ? "rose" : "mint"}>{overview.failed_collections ? `${overview.failed_collections} failed` : "Operational"}</Badge></div><div className="automation-metrics"><span><strong>{overview.sources_collected ?? 0}</strong>sources collected</span><span><strong>{overview.sources_successfully_analyzed ?? 0}</strong>successfully analyzed</span><span><strong>{overview.domain_coverage?.covered ?? 0}</strong>domains covered</span><span><strong>{overview.industry_coverage?.covered ?? 0}</strong>industries covered</span></div><p className="muted-copy">Coverage labels are evidence counts, not competency importance or market representation. Missing evidence does not mean a competency is absent.</p></section><section className="panel"><div className="panel-title-row"><div><p className="eyebrow">PROPOSED KNOWLEDGE</p><h2>Review queue</h2></div><Badge tone="amber">{dashboard?.pending_findings ?? 0}</Badge></div><p className="muted-copy">Automated findings use the same controlled Research Review workflow as administrator-submitted research.</p><button className="button button-secondary" onClick={onOpenReview}>Open Research Review</button></section><section className="panel"><p className="eyebrow">RECENT CHANGE DETECTION</p>{dashboard?.change_events?.length ? dashboard.change_events.map((event) => <div className="automation-change-row" key={event.id}><Badge tone="violet">{event.change_type.replaceAll("_", " ")}</Badge><span><strong>{event.source_name || "Approved source"}</strong><small>{formatDate(event.detected_at)} · {event.source_url}</small></span></div>) : <EmptyState title="No source changes detected" message="Versioned source snapshots will appear after a changed collection." />}</section></div>}{tab === "sources" && <div className="automation-sources-layout"><section className="panel"><SourceForm adminKey={adminKey} onCreated={load} /></section><section className="panel"><div className="panel-title-row"><div><p className="eyebrow">REGISTRY</p><h2>Approved collection endpoints</h2></div><Badge>{sources.length}</Badge></div><SourceRows sources={sources} adminKey={adminKey} onChanged={load} /></section></div>}{tab === "job-search" && <LinkedInJobSearchPanel adminKey={adminKey} onOpenReview={onOpenReview} />}{tab === "runs" && <section className="panel"><div className="panel-title-row"><div><p className="eyebrow">EXECUTION HISTORY</p><h2>Research runs</h2></div><button className="button button-secondary" onClick={load}>Refresh</button></div>{runs.length ? <div className="automation-run-list">{runs.map((run) => <article className="automation-run-row" key={run.id}><div><strong>Run #{run.id}</strong><span>{run.trigger} · started {formatDate(run.started_at || run.created_at)}</span></div><Badge tone={statusTone(run.status)}>{run.status.replaceAll("_", " ")}</Badge><div className="run-counts"><span>{run.sources_collected} collected</span><span>{run.sources_analyzed} analyzed</span><span>{run.duplicates_skipped} duplicates</span><span>{run.failed_collections} failed</span></div></article>)}</div> : <EmptyState title="No research runs" message="Start a manual run or enable a source schedule." />}</section>}{tab === "coverage" && <section className="panel"><div className="panel-title-row"><div><p className="eyebrow">INDUSTRY × DOMAIN × CAREER LEVEL</p><h2>Research coverage matrix</h2></div><div className="review-card-actions"><Badge tone="rose">No research</Badge><Badge tone="amber">Limited</Badge><Badge tone="mint">Adequate</Badge></div></div><p className="muted-copy">Thresholds: limited requires at least one finding; adequate requires at least three findings from two sources.</p><CoverageTable coverage={coverage} /></section>}</>}</>;
}
