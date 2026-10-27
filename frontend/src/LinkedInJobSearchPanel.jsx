import { useEffect, useMemo, useState } from "react";

import {
  createJobSearch,
  fetchJobSearchProviders,
  fetchJobSearchRunResults,
  fetchJobSearchRuns,
  fetchJobSearches,
  importJobSearchResults,
  retryJobSearchRun,
  runJobSearch,
  scheduleJobSearch,
} from "./api";
import { Badge, EmptyState, ErrorState, Loading } from "./components";

const defaultForm = {
  name: "", provider_type: "import", keywords: "Product Security Engineer\nEmbedded Security Engineer\nCloud Security Engineer",
  location: "", experience_level: "", date_posted: "any", employment_type: "", work_mode: "any", max_results: 100,
};

function providerLabel(type) { return { linkedin_authorized: "Authorized LinkedIn", licensed_api: "Licensed job-data provider", employer_ats: "Employer / ATS", import: "Permitted import" }[type] || type; }
function formatDate(value) { return value ? new Date(value).toLocaleString() : "Not yet"; }
function runTone(status) { return status === "completed" ? "mint" : status === "completed_with_errors" || status === "blocked" ? "amber" : status === "failed" ? "rose" : "blue"; }

function Progress({ run }) {
  if (!run) return <EmptyState title="No search run selected" message="Run a saved search to see provider totals and individual processing counts." />;
  const counts = [["Provider total", run.provider_total ?? "Unknown"], ["Results retrieved", run.results_retrieved], ["Unique results", run.unique_results], ["Queued", run.results_queued], ["Descriptions retrieved", run.descriptions_retrieved], ["Successfully analyzed", run.successfully_analyzed], ["Duplicates", run.duplicates_skipped], ["Manual review", run.manual_review_required], ["Failed", run.failed]];
  return <div className="automation-metrics job-search-progress">{counts.map(([label, value]) => <span key={label}><strong>{value}</strong>{label}</span>)}</div>;
}

export default function LinkedInJobSearchPanel({ adminKey, onOpenReview }) {
  const [providers, setProviders] = useState([]);
  const [searches, setSearches] = useState([]);
  const [runs, setRuns] = useState([]);
  const [results, setResults] = useState([]);
  const [selectedSearch, setSelectedSearch] = useState(null);
  const [selectedRun, setSelectedRun] = useState(null);
  const [form, setForm] = useState(defaultForm);
  const [importText, setImportText] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function loadSearches() {
    setLoading(true); setError(null);
    try {
      const [nextProviders, nextSearches] = await Promise.all([fetchJobSearchProviders(adminKey), fetchJobSearches(adminKey)]);
      setProviders(nextProviders); setSearches(nextSearches);
      const nextSearch = nextSearches.find((item) => item.id === selectedSearch?.id) || nextSearches[0] || null;
      setSelectedSearch(nextSearch);
      if (nextSearch) {
        const nextRuns = await fetchJobSearchRuns(nextSearch.id, adminKey);
        setRuns(nextRuns); setSelectedRun(nextRuns[0] || null);
        if (nextRuns[0]) setResults(await fetchJobSearchRunResults(nextRuns[0].id, adminKey));
      }
    } catch (requestError) { setError(requestError); } finally { setLoading(false); }
  }
  useEffect(() => { loadSearches(); }, [adminKey]);

  const selectedProvider = useMemo(() => providers.find((provider) => provider.provider_type === form.provider_type), [providers, form.provider_type]);
  function updateForm(key, value) { setForm((current) => ({ ...current, [key]: value })); }
  async function saveSearch(event) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      await createJobSearch({ ...form, keywords: form.keywords.split("\n").map((value) => value.trim()).filter(Boolean), max_results: Number(form.max_results), search_frequency: "manual", enabled: true }, adminKey);
      setForm(defaultForm); await loadSearches();
    } catch (requestError) { setError(requestError); } finally { setBusy(false); }
  }
  async function searchJobs(search = selectedSearch) {
    if (!search) return;
    setBusy(true); setError(null);
    try { const run = await runJobSearch(search.id, {}, adminKey); setSelectedSearch(search); setSelectedRun(run); setRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]); setResults(await fetchJobSearchRunResults(run.id, adminKey)); await loadSearches(); } catch (requestError) { setError(requestError); } finally { setBusy(false); }
  }
  async function scheduleSearch() {
    if (!selectedSearch) return;
    setBusy(true); setError(null);
    try { await scheduleJobSearch(selectedSearch.id, { frequency: "daily", enabled: true }, adminKey); await loadSearches(); } catch (requestError) { setError(requestError); } finally { setBusy(false); }
  }
  async function showRun(run) {
    setSelectedRun(run); setBusy(true);
    try { setResults(await fetchJobSearchRunResults(run.id, adminKey)); } catch (requestError) { setError(requestError); } finally { setBusy(false); }
  }
  async function importDataset(event) {
    event.preventDefault(); if (!selectedSearch) return;
    setBusy(true); setError(null);
    try { const payload = JSON.parse(importText); const run = await importJobSearchResults(selectedSearch.id, Array.isArray(payload) ? { items: payload } : payload, adminKey); setSelectedRun(run); setImportText(""); await loadSearches(); setResults(await fetchJobSearchRunResults(run.id, adminKey)); } catch (requestError) { setError(requestError instanceof SyntaxError ? new Error("Import must be valid JSON") : requestError); } finally { setBusy(false); }
  }
  async function retry() {
    if (!selectedRun) return;
    setBusy(true); setError(null);
    try { const run = await retryJobSearchRun(selectedRun.id, adminKey); setSelectedRun(run); setRuns((current) => current.map((item) => item.id === run.id ? run : item)); setResults(await fetchJobSearchRunResults(run.id, adminKey)); } catch (requestError) { setError(requestError); } finally { setBusy(false); }
  }

  if (loading) return <section className="panel"><Loading label="Loading job-search providers" /></section>;
  return <div className="job-search-workspace">
    {error && <ErrorState error={error} onRetry={loadSearches} />}
    <section className="panel">
      <div className="panel-title-row"><div><p className="eyebrow">LINKEDIN JOB SEARCH</p><h2>Authorized search results integration</h2></div><Badge tone="violet">No undocumented APIs</Badge></div>
      <p className="muted-copy">Live LinkedIn search is not claimed as operational unless an authorized provider is configured. Use a permitted result URL or exported dataset import when no provider is available.</p>
      <div className="job-provider-grid">{providers.map((provider) => <article className="job-provider-card" key={provider.provider_type}><div className="automation-row-title"><strong>{provider.display_name}</strong><Badge tone={provider.configured ? "mint" : provider.provider_type === "import" ? "blue" : "amber"}>{provider.status}</Badge></div><small>{provider.limitations[0]}</small></article>)}</div>
    </section>
    <section className="panel"><div className="panel-title-row"><div><p className="eyebrow">DEFINE CRITERIA</p><h2>Save a cybersecurity job search</h2></div></div>
      <form className="automation-form" onSubmit={saveSearch}><div className="automation-form-grid"><label>Search name<input required value={form.name} onChange={(event) => updateForm("name", event.target.value)} placeholder="Embedded security roles" /></label><label>Provider<select value={form.provider_type} onChange={(event) => updateForm("provider_type", event.target.value)}>{providers.map((provider) => <option key={provider.provider_type} value={provider.provider_type}>{providerLabel(provider.provider_type)}</option>)}</select></label><label className="automation-wide">Job keywords <span className="hint">one per line</span><textarea required rows="3" value={form.keywords} onChange={(event) => updateForm("keywords", event.target.value)} /></label><label>Location<input value={form.location} onChange={(event) => updateForm("location", event.target.value)} placeholder="Remote or city" /></label><label>Experience level<input value={form.experience_level} onChange={(event) => updateForm("experience_level", event.target.value)} placeholder="Mid-Senior" /></label><label>Date posted<select value={form.date_posted} onChange={(event) => updateForm("date_posted", event.target.value)}><option value="any">Any time</option><option value="24h">Past 24 hours</option><option value="week">Past week</option><option value="month">Past month</option></select></label><label>Employment type<input value={form.employment_type} onChange={(event) => updateForm("employment_type", event.target.value)} placeholder="Full-time" /></label><label>Work mode<select value={form.work_mode} onChange={(event) => updateForm("work_mode", event.target.value)}><option value="any">Any</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">Onsite</option></select></label><label>Maximum results<input type="number" min="1" max="500" value={form.max_results} onChange={(event) => updateForm("max_results", event.target.value)} /></label></div>{selectedProvider && !selectedProvider.configured && form.provider_type !== "import" && <p className="hint">{selectedProvider.display_name} is not configured. Save the criteria, then use the permitted import alternative.</p>}<button className="button" disabled={busy}>{busy ? "Saving…" : "Save Search"}</button></form>
    </section>
    <section className="panel"><div className="panel-title-row"><div><p className="eyebrow">SAVED SEARCHES</p><h2>Search Jobs</h2></div><Badge>{searches.length}</Badge></div>{searches.length ? <div className="job-search-list">{searches.map((search) => <article className={`automation-source-row ${selectedSearch?.id === search.id ? "selected" : ""}`} key={search.id} onClick={() => setSelectedSearch(search)}><div><div className="automation-row-title"><strong>{search.name}</strong><Badge tone={search.provider_status === "configured" ? "mint" : search.provider_type === "import" ? "blue" : "amber"}>{search.provider_status}</Badge></div><span>{search.keywords.join(", ")}</span><small>{search.location || "Any location"} · max {search.max_results} · {search.search_frequency} · next {formatDate(search.next_run_at)}</small></div><div className="automation-row-actions"><button className="button button-secondary" onClick={(event) => { event.stopPropagation(); searchJobs(search); }}>Search Jobs</button></div></article>)}</div> : <EmptyState title="No saved searches" message="Save criteria above to start a permitted job-search workflow." />}</section>
    {selectedSearch && <section className="panel"><div className="panel-title-row"><div><p className="eyebrow">SEARCH CONTROLS</p><h2>{selectedSearch.name}</h2></div><div className="review-card-actions"><button className="button" disabled={busy} onClick={searchJobs}>Search Jobs</button><button className="button button-secondary" disabled={busy} onClick={scheduleSearch}>Schedule Search</button><button className="button button-secondary" onClick={onOpenReview}>Research Review</button></div></div><p className="muted-copy">Provider totals and all subsequent counts below are stored from actual processing records. Search snippets are never treated as complete descriptions.</p><form className="automation-form" onSubmit={importDataset}><label>Import permitted result URLs or exported dataset <span className="hint">JSON array or {`{"items": [...]}`}; complete descriptions are optional</span><textarea rows="4" value={importText} onChange={(event) => setImportText(event.target.value)} placeholder='[{"title":"Product Security Engineer","url":"https://employer.example/jobs/123","description":"..."}]' /></label><button className="button button-secondary" disabled={busy || !importText}>Import Results</button></form></section>}
    {selectedSearch && <section className="panel"><div className="panel-title-row"><div><p className="eyebrow">RESEARCH PROGRESS</p><h2>View Research Progress</h2></div>{selectedRun && <Badge tone={runTone(selectedRun.status)}>{selectedRun.status.replaceAll("_", " ")}</Badge>}</div><Progress run={selectedRun} />{selectedRun && <div className="review-card-actions"><button className="button button-secondary" onClick={retry} disabled={busy || !["completed_with_errors", "failed", "blocked"].includes(selectedRun.status)}>Retry eligible results</button><button className="button button-secondary" onClick={onOpenReview}>View Research Review</button></div>}<h3>View Results</h3>{runs.length ? <div className="automation-run-list">{runs.map((run) => <article className="automation-run-row" key={run.id} onClick={() => showRun(run)}><div><strong>Run #{run.id}</strong><span>{run.trigger} · {formatDate(run.created_at)}</span></div><Badge tone={runTone(run.status)}>{run.status.replaceAll("_", " ")}</Badge><div className="run-counts"><span>{run.results_retrieved} retrieved</span><span>{run.successfully_analyzed} analyzed</span><span>{run.manual_review_required} review</span><span>{run.failed} failed</span></div></article>)}</div> : <EmptyState title="No runs yet" message="Search or import results to begin." />}{selectedRun && results.length > 0 && <div className="job-result-list">{results.map((result) => <article className="automation-change-row" key={result.id}><Badge tone={result.status === "analyzed" ? "mint" : result.status === "manual_review_required" ? "amber" : result.status === "failed" ? "rose" : "violet"}>{result.status.replaceAll("_", " ")}</Badge><span><strong>{result.title}</strong><small><a href={result.canonical_url} target="_blank" rel="noreferrer">{result.canonical_url}</a> · attempts {result.attempt_count}</small>{result.error_message && <small className="error-copy">{result.error_message}</small>}</span></article>)}</div>}</section>}
  </div>;
}
