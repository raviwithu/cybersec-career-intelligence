import { useEffect, useState } from "react";

import { clearAdminSessionKey, fetchKnowledgeMapPreview, fetchKnowledgeReviewQueue, getAdminSessionKey, publishKnowledgeProposal, reviewKnowledgeProposal, setAdminSessionKey } from "./api";
import { Badge, EmptyState, ErrorState, Loading, PageHeader } from "./components";
import { MAP_ACTIONS, MAP_ACTION_LABELS, isMapProposal, lineDiff } from "./knowledgeMapActions";

const sectionLabels = { overview: "Overview", how_it_works: "How It Works", attack_surfaces: "Attack Surfaces", mitigations: "Mitigations", real_world_examples: "Real-World Examples", references: "References", career_level_guidance: "Career Guidance", code_examples: "Code Examples", architecture: "Architecture Diagrams" };

function DiffView({ before, after }) {
  const rows = lineDiff(before, after);
  if (!rows.length) return <p className="muted-copy">No content.</p>;
  return <pre className="kr-diff" aria-label="Before and after differences">{rows.map((row, index) => <span key={index} className={`kr-diff-${row.kind}`}>{row.kind === "added" ? "+ " : row.kind === "removed" ? "- " : "  "}{row.text}{"\n"}</span>)}</pre>;
}

function BranchList({ items, label }) {
  return <div><span className="field-label">{label}</span>{items.length ? <ol>{items.map((item) => <li key={item.topic_id}>{item.name}</li>)}</ol> : <p className="muted-copy">Empty branch</p>}</div>;
}

// Before/after for knowledge map proposals: a text diff of the captured live state and the change, plus the
// affected branches computed by the map-preview endpoint (applied to live data and rolled back, never written).
function MapChangeComparison({ proposal, adminKey }) {
  const [preview, setPreview] = useState({ loading: true, error: null, data: null });
  useEffect(() => {
    let active = true;
    setPreview({ loading: true, error: null, data: null });
    fetchKnowledgeMapPreview(proposal.id, adminKey).then((data) => active && setPreview({ loading: false, error: null, data })).catch((error) => active && setPreview({ loading: false, error, data: null }));
    return () => { active = false; };
  }, [proposal.id, proposal.version, adminKey]);
  return <div className="kr-map-change">
    <div><span className="field-label">Change: current state (−) and proposed change (+)</span><DiffView before={proposal.original_content} after={proposal.proposed_content} /></div>
    <div><span className="field-label">Affected branches</span>
      {preview.loading ? <Loading label="Computing map preview" /> : preview.error ? <p className="muted-copy">Preview unavailable: {preview.error.message}</p>
        : preview.data.branches.length ? preview.data.branches.map((branch) => <article className="kr-branch" key={`${branch.domain_id}-${branch.map_branch}`}><strong>{branch.domain_name} › {branch.label}</strong><div className="kr-branch-columns"><BranchList items={branch.before} label="Before" /><BranchList items={branch.after} label="After publish" /></div></article>)
          : <p className="muted-copy">{preview.data.message || "No map branch changes; the change affects topic details only."}</p>}
    </div>
  </div>;
}

export default function KnowledgeReviewPage() {
  const [enteredKey, setEnteredKey] = useState(() => getAdminSessionKey());
  const [adminKey, setAdminKey] = useState(() => getAdminSessionKey());
  const [filters, setFilters] = useState({ source_type: "", action: "", status: "" });
  const [tab, setTab] = useState("all");
  const [queue, setQueue] = useState({ items: [], counts: {} });
  const [selectedId, setSelectedId] = useState(null);
  const [verifiedSourceIds, setVerifiedSourceIds] = useState([]);
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  async function load() {
    if (!adminKey) return;
    setBusy(true); setError(null);
    try {
      const result = await fetchKnowledgeReviewQueue(tab === "map" ? { ...filters, group: "map" } : filters, adminKey);
      setQueue(result);
      if (!selectedId && result.items.length) {
        setSelectedId(result.items[0].id);
        setVerifiedSourceIds(result.items[0].references.filter((reference) => ["verified", "authoritative"].includes(reference.verification_status)).map((reference) => reference.id));
      }
    } catch (requestError) { setError(requestError); } finally { setBusy(false); }
  }
  useEffect(() => { load(); }, [adminKey, filters.source_type, filters.action, filters.status, tab]);
  function changeTab(next) { setTab(next); setSelectedId(null); setEditing(null); setFilters({ ...filters, action: "" }); }
  const selected = queue.items.find((item) => item.id === selectedId) || null;
  function unlock() { if (enteredKey.trim()) { setAdminSessionKey(enteredKey.trim()); setAdminKey(enteredKey.trim()); } }
  function lock() { clearAdminSessionKey(); setEnteredKey(""); setAdminKey(""); }
  function selectProposal(item) {
    setSelectedId(item.id);
    setVerifiedSourceIds(item.references.filter((reference) => ["verified", "authoritative"].includes(reference.verification_status)).map((reference) => reference.id));
    setEditing(null);
  }
  function toggleVerifiedSource(sourceId) {
    setVerifiedSourceIds((current) => current.includes(sourceId) ? current.filter((id) => id !== sourceId) : [...current, sourceId]);
  }
  async function review(action, verifySources = false) {
    if (!selected) return;
    setBusy(true); setError(null); setNotice(null);
    try { await reviewKnowledgeProposal(selected.id, { expected_version: selected.version, action, reviewer_note: `${action} by administrator.`, ...(action === "modify" ? { proposed_content: editing } : {}), ...(verifySources ? { verified_source_ids: verifiedSourceIds } : {}) }, adminKey); setNotice(verifySources ? "Selected sources verified and proposal approved." : `Proposal ${{ approve: "approved", modify: "modified", defer: "deferred", reject: "rejected" }[action] || action} and retained in review history.`); setEditing(null); await load(); } catch (requestError) { setError(requestError); } finally { setBusy(false); }
  }
  async function publish() {
    if (!selected || selected.status !== "approved") return;
    setBusy(true); setError(null); setNotice(null);
    try { await publishKnowledgeProposal(selected.id, { confirm: true, expected_version: selected.version, change_reason: "Published after administrator review." }, adminKey); setNotice("Proposal published transactionally."); await load(); } catch (requestError) { setError(requestError); } finally { setBusy(false); }
  }
  if (!adminKey) return <><PageHeader eyebrow="ADMINISTRATION / KNOWLEDGE REVIEW" title="Knowledge Review" description="Review proposed section-level knowledge changes before they can affect published pages." /><section className="panel research-auth"><p className="eyebrow">ADMINISTRATOR ACCESS</p><h2>Unlock Knowledge Review</h2><p className="muted-copy">Proposal credentials can submit and inspect status, but only the administrator can review or publish.</p><input aria-label="Administrator API key" type="password" value={enteredKey} onChange={(event) => setEnteredKey(event.target.value)} placeholder="X-Admin-API-Key" /><button className="button" disabled={!enteredKey.trim()} onClick={unlock}>Open Knowledge Review</button></section></>;
  return <>
    <PageHeader eyebrow="ADMINISTRATION / KNOWLEDGE REVIEW" title="Knowledge Review" description="Compare proposed technical claims with published content, inspect provenance, and publish only explicit administrator decisions."><button className="button button-secondary" onClick={lock}>Lock workspace</button></PageHeader>
    {error && <ErrorState error={error} onRetry={load} />}{notice && <p className="success-copy" role="status">{notice}</p>}
    <div className="automation-tabs" role="tablist" aria-label="Proposal groups">{[["all", "All proposals"], ["map", "Mind Map Changes"]].map(([id, label]) => <button type="button" role="tab" key={id} aria-selected={tab === id} className={tab === id ? "active" : ""} onClick={() => changeTab(id)}>{label}</button>)}</div>
    <section className="panel knowledge-review-toolbar"><div className="review-filters"><label>Source type<select value={filters.source_type} onChange={(event) => setFilters({ ...filters, source_type: event.target.value })}><option value="">All sources</option><option value="manual">Manual</option><option value="jsearch">JSearch</option><option value="ai">AI analysis</option><option value="rag">RAG</option><option value="connector">Connector</option></select></label><label>Action<select value={filters.action} onChange={(event) => setFilters({ ...filters, action: event.target.value })}><option value="">All actions</option><option value="CREATE_TOPIC">Create topic</option><option value="UPDATE_SECTION">Update section</option><option value="ADD_SECTION">Add section</option><option value="ADD_ATTACK_SURFACE">Add attack surface</option><option value="ADD_MITIGATION">Add mitigation</option><option value="ADD_REFERENCE">Add reference</option>{MAP_ACTIONS.map((action) => <option key={action} value={action}>{MAP_ACTION_LABELS[action]}</option>)}</select></label><label>Status<select value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}><option value="">All statuses</option><option value="review">Review</option><option value="approved">Approved</option><option value="published">Published</option><option value="rejected">Rejected</option><option value="deferred">Deferred</option></select></label></div><div className="knowledge-review-counts">{Object.entries(queue.counts).map(([status, count]) => <Badge key={status}>{status}: {count}</Badge>)}</div></section>
    {busy && !queue.items.length ? <Loading label="Loading knowledge proposals" /> : <div className="knowledge-review-layout"><section className="panel knowledge-review-list"><div className="panel-title-row"><div><p className="eyebrow">PROPOSALS</p><h2>{queue.total} review items</h2></div></div>{queue.items.length ? queue.items.map((item) => <button type="button" className={`knowledge-review-row ${selectedId === item.id ? "selected" : ""}`} key={item.id} onClick={() => selectProposal(item)}><span><strong>{item.topic_key || item.proposed_content?.topic?.name || "New topic"}</strong><small>{isMapProposal(item) ? MAP_ACTION_LABELS[item.action] : sectionLabels[item.section] || item.section || "Topic metadata"} · {item.source_type} · v{item.version}</small></span><Badge tone={item.status === "approved" ? "mint" : item.status === "rejected" ? "rose" : "amber"}>{item.status}</Badge></button>) : <EmptyState title="No proposals match" message="Change the filters or submit a new knowledge proposal." />}</section><section className="knowledge-review-detail">{selected ? <article className="panel"><div className="panel-title-row"><div><p className="eyebrow">{selected.action}</p><h2>{selected.topic_key || "New topic proposal"}</h2><p className="muted-copy">{isMapProposal(selected) ? MAP_ACTION_LABELS[selected.action] : sectionLabels[selected.section] || "Topic metadata"} · {selected.source_type} · submitted {new Date(selected.created_at).toLocaleString()}{selected.submitted_by ? ` by ${selected.submitted_by}` : ""}</p>{selected.change_reason && <p className="kr-reason"><span className="field-label">Change reason</span>{selected.change_reason}</p>}</div><Badge tone={selected.status === "approved" ? "mint" : selected.status === "rejected" ? "rose" : "amber"}>{selected.status}</Badge></div>{isMapProposal(selected) && !editing ? <MapChangeComparison proposal={selected} adminKey={adminKey} /> : <div className="knowledge-comparison"><div><span className="field-label">Existing published content</span>{selected.original_content ? <pre>{JSON.stringify(selected.original_content, null, 2)}</pre> : <p className="muted-copy">No published content exists yet.</p>}</div><div><span className="field-label">Proposed content</span>{editing ? <textarea className="knowledge-json-editor" value={JSON.stringify(editing, null, 2)} onChange={(event) => { try { setEditing(JSON.parse(event.target.value)); } catch { /* preserve text until valid JSON */ } }} /> : <pre>{JSON.stringify(selected.proposed_content, null, 2)}</pre>}</div></div>}<section className="knowledge-provenance"><div className="panel-title-row"><div><span className="field-label">Supporting references</span><p className="muted-copy">Unverified and AI-derived sources remain proposals, not published evidence.</p></div></div>{selected.references.length ? selected.references.map((reference) => <article className="knowledge-reference-row" key={reference.id}><div><strong>{reference.title}</strong><small>{reference.source_type} · {reference.locator || "No locator"}</small></div><Badge tone={reference.verification_status === "verified" || reference.verification_status === "authoritative" ? "mint" : "amber"}>{reference.verification_status}</Badge><label><input type="checkbox" aria-label={`Verify ${reference.title}`} checked={verifiedSourceIds.includes(reference.id)} onChange={() => toggleVerifiedSource(reference.id)} /> Verify this source</label>{reference.excerpt && <blockquote>“{reference.excerpt}”</blockquote>}</article>) : <p className="muted-copy">No supporting references supplied.</p>}</section><div className="review-card-actions">{["review", "deferred"].includes(selected.status) && <><button className="button" disabled={busy} onClick={() => review("approve")}>Approve</button>{selected.references.length > 0 && <button className="button button-secondary" disabled={busy || !verifiedSourceIds.length} onClick={() => review("approve", true)}>Verify selected sources & approve</button>}<button className="button button-secondary" disabled={busy} onClick={() => { setEditing(selected.proposed_content); }}>Modify</button><button className="button button-secondary" disabled={busy} onClick={() => review("defer")}>Defer</button><button className="button button-danger" disabled={busy} onClick={() => review("reject")}>Reject</button></>}{editing && <button className="button" disabled={busy} onClick={() => review("modify")}>Save modified proposal</button>}{selected.status === "approved" && <button className="button" disabled={busy} onClick={publish}>Publish approved proposal</button>}</div></article> : <section className="panel"><EmptyState title="Select a proposal" message="Choose a proposal to compare content and supporting provenance." /></section>}</section></div>}
  </>;
}
