import { useEffect, useMemo, useState } from "react";

import {
  bulkReviewYahooCandidates,
  clearAdminSessionKey,
  disconnectYahooConnection,
  fetchYahooAlertSources,
  fetchYahooCandidate,
  fetchYahooCandidates,
  fetchYahooConnections,
  fetchYahooSyncRuns,
  getAdminSessionKey,
  retryYahooDescription,
  reviewYahooCandidate,
  saveYahooConnection,
  setAdminSessionKey,
  syncYahooConnection,
  testYahooConnection,
  updateYahooAlertSource,
  updateYahooCandidate,
  updateYahooConnection,
} from "./api";
import { Badge, EmptyState, ErrorState, Loading, PageHeader, StatCard } from "./components";

const ALLOWED_SENDER = "jobalerts-noreply@linkedin.com";
const BULK_BATCH_SIZE = 100;
const TABS = [["inbox", "Job Inbox"], ["connection", "Mail Connection"], ["sources", "Alert Sources"], ["history", "Sync History"]];

// datetime-local inputs hold local wall-clock time; the API stores UTC.
function toLocalInput(value) { if (!value) return ""; const date = new Date(value); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16); }
function formatDate(value) { return value ? new Date(value).toLocaleString() : "Not yet"; }
function tone(value) { return ["approved", "completed", "analyzed", "connected"].includes(value) ? "mint" : ["rejected", "failed", "error"].includes(value) ? "rose" : "amber"; }

function bulkSummary(action, totals) {
  if (action !== "approve") return `${totals.updated} job(s) ${action === "reject" ? "rejected" : "deferred"}.`;
  const parts = [`${totals.approved} approved`];
  if (totals.fetching_description) parts.push(`${totals.fetching_description} fetching full descriptions (approved automatically when retrieved, otherwise returned to pending with a note)`);
  if (totals.skipped_duplicates) parts.push(`${totals.skipped_duplicates} duplicate(s) skipped`);
  if (totals.skipped_already_approved) parts.push(`${totals.skipped_already_approved} already approved`);
  return `${parts.join(" · ")}.`;
}

function AuthGate({ onUnlock }) {
  const [value, setValue] = useState("");
  return <section className="panel research-auth"><p className="eyebrow">ADMINISTRATOR ACCESS</p><h2>Unlock Yahoo Job Alerts</h2><p className="muted-copy">The Yahoo integration is administrator-only. Credentials stay in the backend and are never returned to this page.</p><input aria-label="Administrator API key" type="password" value={value} onChange={(event) => setValue(event.target.value)} placeholder="X-Admin-API-Key" /><button className="button" disabled={!value} onClick={() => { setAdminSessionKey(value); onUnlock(value); }}>Open Yahoo Job Alerts</button></section>;
}

function CandidateDrawer({ candidate, adminKey, onChanged, onClose }) {
  const [form, setForm] = useState({ title: candidate.title, employer: candidate.employer, location: candidate.location, work_mode: candidate.work_mode, job_url: candidate.job_url, description_text: candidate.description_text });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function save() { setBusy(true); setError(null); try { await updateYahooCandidate(candidate.id, form, adminKey); await onChanged(); } catch (requestError) { setError(requestError); } finally { setBusy(false); } }
  async function action(kind, payload = {}) { setBusy(true); setError(null); try { await reviewYahooCandidate(candidate.id, kind, payload, adminKey); await onChanged(); onClose(); } catch (requestError) { setError(requestError); } finally { setBusy(false); } }
  async function retry() { setBusy(true); setError(null); try { await retryYahooDescription(candidate.id, adminKey); await onChanged(); } catch (requestError) { setError(requestError); } finally { setBusy(false); } }
  return <div className="drawer-backdrop" role="presentation" onClick={onClose}><aside className="job-drawer panel" role="dialog" aria-label="Job candidate details" onClick={(event) => event.stopPropagation()}><div className="panel-title-row"><div><p className="eyebrow">JOB CANDIDATE #{candidate.id}</p><h2>{candidate.title}</h2></div><button className="button button-secondary" onClick={onClose}>Close</button></div>{error && <ErrorState error={error} />}<div className="drawer-badges"><Badge tone={tone(candidate.review_status)}>{candidate.review_status}</Badge><Badge tone={candidate.description_complete ? "mint" : "amber"}>{candidate.description_complete ? "Full description" : "Partial description"}</Badge>{candidate.duplicate_status === "duplicate" && <Badge tone="violet">Duplicate</Badge>}</div><div className="job-detail-grid"><label>Title<input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label><label>Employer<input value={form.employer} onChange={(event) => setForm({ ...form, employer: event.target.value })} /></label><label>Location<input value={form.location} onChange={(event) => setForm({ ...form, location: event.target.value })} /></label><label>Work mode<input value={form.work_mode} onChange={(event) => setForm({ ...form, work_mode: event.target.value })} /></label><label className="drawer-wide">Original posting link<input value={form.job_url} onChange={(event) => setForm({ ...form, job_url: event.target.value })} /></label><label className="drawer-wide">Description<textarea rows="12" value={form.description_text} onChange={(event) => setForm({ ...form, description_text: event.target.value })} /></label></div><div className="drawer-meta"><span><strong>Alert source</strong>{candidate.source_provider}</span><span><strong>From</strong>{candidate.alert_sender}</span><span><strong>Received</strong>{formatDate(candidate.alert_received_at)}</span><span><strong>Extraction</strong>{candidate.extraction_method}</span><span><strong>Ingestion</strong>{candidate.ingestion_status}</span></div><div className="drawer-provenance"><strong>Provenance</strong>{candidate.provenance.map((item, index) => <span key={`${item.type}-${index}`}>{item.source_label}{item.provider_job_id ? ` · ${item.provider_job_id}` : ""}</span>)}</div><div className="review-card-actions"><button className="button button-secondary" disabled={busy} onClick={save}>Save corrections</button>{!candidate.description_complete && <button className="button button-secondary" disabled={busy} onClick={retry}>Retry description</button>}<button className="button" disabled={busy || candidate.review_status === "approved"} onClick={() => action("approve", { note: "", allow_partial: false })}>Approve for ingestion</button><button className="button button-secondary" disabled={busy} onClick={() => action("defer")}>Defer</button><button className="button button-danger" disabled={busy} onClick={() => action("reject")}>Reject</button></div><p className="muted-copy">Approved complete descriptions queue into the existing AI analysis pipeline. Research Review approval remains mandatory; findings are never auto-published.</p></aside></div>;
}

function Inbox({ candidates, counts, filters, setFilters, selected, setSelected, onRefresh, onOpen, adminKey }) {
  const [busy, setBusy] = useState(false);
  const [bulkMessage, setBulkMessage] = useState(null);
  const visibleIds = candidates.map((item) => item.id);
  const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selected.includes(id));
  async function bulk(action) {
    if (!selected.length || !window.confirm(`${action} ${selected.length} selected job(s)?`)) return;
    setBusy(true);
    setBulkMessage(null);
    const totals = { updated: 0, approved: 0, fetching_description: 0, skipped_duplicates: 0, skipped_already_approved: 0 };
    let done = [];
    try {
      // The API accepts at most BULK_BATCH_SIZE ids per request.
      for (let start = 0; start < selected.length; start += BULK_BATCH_SIZE) {
        const batch = selected.slice(start, start + BULK_BATCH_SIZE);
        const result = await bulkReviewYahooCandidates({ candidate_ids: batch, action, note: "Bulk administrator review" }, adminKey);
        Object.keys(totals).forEach((key) => { totals[key] += result[key] || 0; });
        done = [...done, ...batch];
      }
      setBulkMessage({ tone: "info", text: bulkSummary(action, totals) });
    } catch (requestError) {
      setBulkMessage({ tone: "error", text: `${done.length} of ${selected.length} job(s) processed before an error: ${requestError.message}` });
    } finally {
      setSelected(selected.filter((id) => !done.includes(id)));
      setBusy(false);
      await onRefresh();
    }
  }
  return <><section className="stats-grid yahoo-stats"><StatCard label="Emails scanned" value={counts.emails} detail="Matching mailbox messages" accent="blue" /><StatCard label="Alerts identified" value={counts.alerts} detail="Exact LinkedIn sender" accent="violet" /><StatCard label="Jobs extracted" value={counts.jobs} detail="Individual listings" accent="mint" /><StatCard label="Pending approval" value={counts.pending} detail="Administrator review" accent="amber" /></section><section className="panel"><div className="panel-title-row"><div><p className="eyebrow">LINKEDIN JOB ALERTS</p><h2>Job Inbox</h2><p className="muted-copy">Email Source: LinkedIn Job Alerts · Allowed Sender: <code>{ALLOWED_SENDER}</code></p></div><button className="button button-secondary" onClick={onRefresh}>Refresh</button></div><div className="job-filters"><select aria-label="Candidate status" value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}><option value="">All statuses</option><option value="pending">Pending</option><option value="approved">Approved</option><option value="rejected">Rejected</option><option value="deferred">Deferred</option></select><select aria-label="Description completeness" value={filters.description} onChange={(event) => setFilters({ ...filters, description: event.target.value })}><option value="">All descriptions</option><option value="complete">Full description</option><option value="partial">Partial description</option></select><input aria-label="Search jobs" placeholder="Search title, employer, location" value={filters.search} onChange={(event) => setFilters({ ...filters, search: event.target.value })} /><button className="button button-secondary" disabled={!selected.length || busy} onClick={() => bulk("approve")}>Approve {selected.length || "selected"}</button><button className="button button-secondary" disabled={!selected.length || busy} onClick={() => bulk("defer")}>Defer</button><button className="button button-danger" disabled={!selected.length || busy} onClick={() => bulk("reject")}>Reject</button></div>{bulkMessage && <p className={bulkMessage.tone === "error" ? "error-copy" : "muted-copy"} role="status">{bulkMessage.text}</p>}{candidates.length ? <div className="job-table-wrap"><table className="job-table"><thead><tr><th><input type="checkbox" aria-label="Select all visible jobs" checked={allSelected} onChange={() => setSelected(allSelected ? selected.filter((id) => !visibleIds.includes(id)) : [...new Set([...selected, ...visibleIds])])} /></th><th>Job</th><th>Location</th><th>Source</th><th>Description</th><th>Discovered</th><th>Status</th></tr></thead><tbody>{candidates.map((candidate) => <tr key={candidate.id} onClick={() => onOpen(candidate.id)}><td onClick={(event) => event.stopPropagation()}><input type="checkbox" aria-label={`Select ${candidate.title}`} checked={selected.includes(candidate.id)} onChange={() => setSelected(selected.includes(candidate.id) ? selected.filter((id) => id !== candidate.id) : [...selected, candidate.id])} /></td><td><strong>{candidate.title}</strong><small>{candidate.employer || "Employer not extracted"}</small></td><td>{candidate.location || "Not specified"}</td><td>{candidate.source_provider}</td><td><Badge tone={candidate.description_complete ? "mint" : "amber"}>{candidate.ingestion_status === "fetching_description" ? "Fetching" : candidate.description_complete ? "Full" : "Partial"}</Badge></td><td>{formatDate(candidate.first_seen_at)}</td><td><Badge tone={tone(candidate.review_status)}>{candidate.review_status}</Badge>{candidate.duplicate_status === "duplicate" && <Badge tone="violet">Duplicate</Badge>}</td></tr>)}</tbody></table></div> : <EmptyState title="No job candidates" message="Run a historical or incremental synchronization to discover LinkedIn job alerts." />}</section></>;
}

function ConnectionTab({ connections, runs, adminKey, onRefresh }) {
  const current = connections[0];
  const [form, setForm] = useState({ email_address: current?.email_address || "", app_password: "", folder: current?.folder || "Inbox", initial_sync_from: toLocalInput(current?.initial_sync_from), automatic_sync_enabled: current?.automatic_sync_enabled || false, sync_interval_minutes: current?.sync_interval_minutes || 360 });
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (current) setForm((value) => ({ ...value, email_address: current.email_address, folder: current.folder, automatic_sync_enabled: current.automatic_sync_enabled, sync_interval_minutes: current.sync_interval_minutes, initial_sync_from: toLocalInput(current.initial_sync_from) })); }, [current?.id]);
  async function test() { setBusy(true); try { const result = await testYahooConnection({ email_address: form.email_address, auth_method: "app_password", app_password: form.app_password, folder: form.folder }, adminKey); setMessage(result.detail); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  async function save() { setBusy(true); try { const payload = { ...form, initial_sync_from: form.initial_sync_from ? new Date(form.initial_sync_from).toISOString() : null, sync_interval_minutes: Number(form.sync_interval_minutes) }; if (current) { if (!payload.app_password) delete payload.app_password; await updateYahooConnection(current.id, payload, adminKey); } else await saveYahooConnection(payload, adminKey); setForm({ ...form, app_password: "" }); setMessage("Connection saved. The app password is encrypted in the backend."); await onRefresh(); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  async function sync(mode, last_days) { if (!current) return; setBusy(true); try { await syncYahooConnection(current.id, { mode, last_days }, adminKey); setMessage("Synchronization completed; refresh to view candidates and history."); await onRefresh(); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  async function disconnect() { if (!current || !window.confirm("Disconnect Yahoo Mail? Existing candidates and provenance remain.")) return; await disconnectYahooConnection(current.id, adminKey); await onRefresh(); }
  return <div className="yahoo-connection-layout"><section className="panel"><div className="panel-title-row"><div><p className="eyebrow">BACKEND-ONLY IMAP OVER TLS</p><h2>Yahoo Mail Connection</h2></div>{current && <Badge tone={tone(current.status)}>{current.status}</Badge>}</div><p className="muted-copy">Yahoo officially documents <code>imap.mail.yahoo.com:993</code> with SSL/TLS and an app password for third-party mail clients. The primary Yahoo password is never requested.</p><div className="connection-form"><label>Yahoo email address<input type="email" value={form.email_address} disabled={Boolean(current)} onChange={(event) => setForm({ ...form, email_address: event.target.value })} /></label><label>Authentication method<select value="app_password" disabled><option>App password</option></select></label><label>App password<input type="password" autoComplete="new-password" value={form.app_password} onChange={(event) => setForm({ ...form, app_password: event.target.value })} placeholder={current ? "Leave blank to keep current credential" : "Yahoo-generated app password"} /></label><label>Mailbox folder<input value={form.folder} onChange={(event) => setForm({ ...form, folder: event.target.value })} /></label><label>Initial sync date<input type="datetime-local" value={form.initial_sync_from} onChange={(event) => setForm({ ...form, initial_sync_from: event.target.value })} /></label><label>Sync interval (minutes)<input type="number" min="15" max="10080" value={form.sync_interval_minutes} onChange={(event) => setForm({ ...form, sync_interval_minutes: event.target.value })} /></label><label className="checkbox-label"><input type="checkbox" checked={form.automatic_sync_enabled} onChange={(event) => setForm({ ...form, automatic_sync_enabled: event.target.checked })} /> Automatic incremental sync</label></div>{message && <p className="muted-copy">{message}</p>}<div className="review-card-actions"><button className="button button-secondary" disabled={busy || !form.app_password} onClick={test}>Test Connection</button><button className="button" disabled={busy || !form.email_address || (!current && !form.app_password)} onClick={save}>Save Connection</button>{current && <><button className="button button-secondary" disabled={busy} onClick={() => sync("initial", 7)}>Sync last 7 days</button><button className="button button-secondary" disabled={busy} onClick={() => sync("initial", 30)}>Sync last 30 days</button><button className="button button-secondary" disabled={busy} onClick={() => sync("initial", 90)}>Sync last 90 days</button><button className="button button-danger" disabled={busy} onClick={disconnect}>Disconnect</button></>}</div></section><section className="panel"><p className="eyebrow">CURRENT STATUS</p><h2>{current ? "Checkpointed mailbox" : "No connection configured"}</h2>{current ? <div className="drawer-meta"><span><strong>Last successful sync</strong>{formatDate(current.last_successful_sync)}</span><span><strong>Messages scanned</strong>{current.messages_scanned}</span><span><strong>Alerts detected</strong>{current.alerts_detected}</span><span><strong>Jobs extracted</strong>{current.jobs_extracted}</span><span><strong>Next automatic sync</strong>{formatDate(current.next_sync_at)}</span></div> : <p className="muted-copy">Create a connection with a Yahoo app password to begin. Credentials never appear in API responses.</p>}{current?.last_sync_error && <p className="error-copy">{current.last_sync_error}</p>}<h3>Recent runs</h3>{runs.slice(0, 5).map((run) => <div className="automation-run-row" key={run.id}><span>#{run.id} · {run.mode}</span><Badge tone={tone(run.status)}>{run.status}</Badge></div>)}</section></div>;
}

function SourcesTab({ sources, adminKey, onRefresh }) {
  const source = sources[0];
  const [pattern, setPattern] = useState(source?.subject_pattern || "");
  useEffect(() => setPattern(source?.subject_pattern || ""), [source?.id]);
  if (!source) return <EmptyState title="Connect Yahoo Mail first" message="The fixed LinkedIn Job Alerts rule is created with the mailbox connection." />;
  return <section className="panel"><div className="panel-title-row"><div><p className="eyebrow">FIXED SOURCE RESTRICTION</p><h2>LinkedIn Job Alerts</h2></div><Badge tone={source.enabled ? "mint" : "rose"}>{source.enabled ? "Enabled" : "Disabled"}</Badge></div><div className="source-rule-card"><span><strong>Email Source</strong>LinkedIn Job Alerts</span><span><strong>Allowed Sender</strong><code>{ALLOWED_SENDER}</code></span><span><strong>Adapter</strong>{source.extraction_adapter}</span><span><strong>Alerts detected</strong>{source.detection_count}</span></div><label>Optional subject filter<input value={pattern} onChange={(event) => setPattern(event.target.value)} placeholder="e.g. jobs you may be interested in" /></label><label className="checkbox-label"><input type="checkbox" checked={source.enabled} onChange={async (event) => { await updateYahooAlertSource(source.id, { subject_pattern: pattern, enabled: event.target.checked }, adminKey); await onRefresh(); }} /> Process matching LinkedIn alert emails</label><button className="button" onClick={async () => { await updateYahooAlertSource(source.id, { subject_pattern: pattern, enabled: source.enabled }, adminKey); await onRefresh(); }}>Save source rule</button><p className="muted-copy">Sender filtering is fixed at the IMAP server query and exact normalized From-header validation. Other LinkedIn addresses, Indeed, Glassdoor, unrelated mail, and substring matches are rejected.</p></section>;
}

function HistoryTab({ runs, onRefresh }) {
  return <section className="panel"><div className="panel-title-row"><div><p className="eyebrow">AUDITABLE SYNCHRONIZATION</p><h2>Sync History</h2></div><button className="button button-secondary" onClick={onRefresh}>Refresh</button></div>{runs.length ? <div className="job-table-wrap"><table className="job-table"><thead><tr><th>Run</th><th>Mailbox</th><th>Dates</th><th>Scanned</th><th>Alerts</th><th>Jobs</th><th>Duplicates</th><th>Errors</th><th>Status</th></tr></thead><tbody>{runs.map((run) => <tr key={run.id}><td>#{run.id}<small>{run.mode}</small></td><td>{run.mailbox}</td><td>{formatDate(run.date_from)} – {formatDate(run.date_to)}</td><td>{run.messages_scanned}</td><td>{run.alerts_detected}</td><td>{run.jobs_extracted}</td><td>{run.duplicates}</td><td>{run.errors}</td><td><Badge tone={tone(run.status)}>{run.status}</Badge>{run.error_message && <small className="error-copy">{run.error_message}</small>}</td></tr>)}</tbody></table></div> : <EmptyState title="No synchronization runs" message="Initial and incremental runs will appear here." />}</section>;
}

export default function YahooJobAlertsPage() {
  const [adminKey, setAdminKey] = useState(() => getAdminSessionKey());
  const [enteredKey, setEnteredKey] = useState(() => getAdminSessionKey());
  const [tab, setTab] = useState("inbox");
  const [candidates, setCandidates] = useState([]);
  const [counts, setCounts] = useState({ emails: 0, alerts: 0, jobs: 0, pending: 0 });
  const [connections, setConnections] = useState([]);
  const [runs, setRuns] = useState([]);
  const [sources, setSources] = useState([]);
  const [filters, setFilters] = useState({ status: "", search: "", description: "" });
  const [selected, setSelected] = useState([]);
  const [drawer, setDrawer] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  async function load() { if (!adminKey) return; setLoading(true); setError(null); try { const [candidatePage, nextConnections, nextRuns, nextSources] = await Promise.all([fetchYahooCandidates({ status: filters.status, search: filters.search, description: filters.description }, adminKey), fetchYahooConnections(adminKey), fetchYahooSyncRuns({}, adminKey), fetchYahooAlertSources({}, adminKey)]); setCandidates(candidatePage.items); setCounts({ emails: nextConnections[0]?.messages_scanned || 0, alerts: nextConnections[0]?.alerts_detected || 0, jobs: nextConnections[0]?.jobs_extracted || 0, pending: candidatePage.counts.pending || 0 }); setConnections(nextConnections); setRuns(nextRuns); setSources(nextSources); } catch (requestError) { setError(requestError); } finally { setLoading(false); } }
  useEffect(() => { load(); }, [adminKey, filters.status, filters.search, filters.description]);
  async function openCandidate(id) { try { setDrawer(await fetchYahooCandidate(id, adminKey)); } catch (requestError) { setError(requestError); } }
  async function refreshDrawer() { await load(); if (drawer) setDrawer(await fetchYahooCandidate(drawer.id, adminKey)); }
  if (!adminKey) return <><PageHeader eyebrow="RESEARCH ADMIN / INGESTION" title="Yahoo Job Alerts" description="Discover LinkedIn job alerts through a secure Yahoo Mail connection, review individual jobs, and queue approved descriptions into research ingestion." /><AuthGate onUnlock={(key) => { setAdminKey(key); setEnteredKey(key); }} /></>;
  return <><PageHeader eyebrow="RESEARCH ADMIN / INGESTION" title="Yahoo Job Alerts" description="Yahoo Mail → LinkedIn Alerts → Individual Jobs → Administrator Approval → Research Ingestion → AI Analysis → Research Review."><div className="review-card-actions"><Badge tone="violet">Administrator workspace</Badge><button className="button button-secondary" onClick={() => { clearAdminSessionKey(); setAdminKey(""); setEnteredKey(""); }}>Lock workspace</button></div></PageHeader>{error && <ErrorState error={error} onRetry={load} />}{loading && !connections.length && !candidates.length ? <section className="panel"><Loading label="Loading Yahoo Job Alerts" /></section> : <><div className="ingestion-tabs yahoo-tabs" role="tablist" aria-label="Yahoo Job Alerts sections">{TABS.map(([id, label]) => <button type="button" role="tab" aria-selected={tab === id} className={tab === id ? "active" : ""} key={id} onClick={() => setTab(id)}>{label}</button>)}</div>{tab === "inbox" && <Inbox candidates={candidates} counts={counts} filters={filters} setFilters={setFilters} selected={selected} setSelected={setSelected} onRefresh={load} onOpen={openCandidate} adminKey={adminKey} />}{tab === "connection" && <ConnectionTab connections={connections} runs={runs} adminKey={adminKey} onRefresh={load} />}{tab === "sources" && <SourcesTab sources={sources} adminKey={adminKey} onRefresh={load} />}{tab === "history" && <HistoryTab runs={runs} onRefresh={load} />}</>}{drawer && <CandidateDrawer candidate={drawer} adminKey={adminKey} onChanged={refreshDrawer} onClose={() => setDrawer(null)} />}</>;
}
