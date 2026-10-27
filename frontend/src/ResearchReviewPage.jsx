import { useEffect, useMemo, useState } from "react";

import {
  acceptResearchReviewChange,
  fetchResearchPublicationPreview,
  fetchResearchReviewDashboard,
  fetchResearchReviewSubmission,
  modifyResearchReviewChange,
  publishResearchReview,
  rejectResearchReviewChange,
  clearAdminSessionKey,
  getAdminSessionKey,
  setAdminSessionKey,
} from "./api";
import { Badge, EmptyState, ErrorState, Loading, PageHeader } from "./components";

const emptyFilters = { domain_id: "", subdomain_id: "", career_level_id: "", category_id: "", source_id: "", review_status: "", change_type: "" };

function confidenceLabel(value) {
  if (value === null || value === undefined) return "Not provided";
  return `${Math.round(value * 100)}% confidence`;
}

function statusTone(status) {
  return status === "published" || status === "accepted" || status === "modified" || status === "merged" ? "mint" : status === "rejected" ? "rose" : "amber";
}

const gapLabels = { domain: "security domain", career_level: "career level", category: "competency category", competency: "competency match", competency_name: "competency name", expectation_description: "expectation description" };

function ChangeSummary({ change }) {
  if (!change) return null;
  return <div className="review-change-summary"><div><Badge tone={statusTone(change.status)}>{change.status}</Badge><Badge tone="violet">{change.change_type.replaceAll("_", " ")}</Badge></div><strong>{change.proposed?.competency_name || "Unclassified competency"}</strong><span>Review version {change.version} · {change.evidence_count ?? change.proposed?.evidence?.length ?? 0} evidence item{(change.evidence_count ?? change.proposed?.evidence?.length ?? 0) === 1 ? "" : "s"}</span></div>;
}

function FindingCard({ finding, onInspect, onEdit, onAccept, onReject, busy, error, children }) {
  const change = finding.review_change;
  const locked = !change || ["published", "rejected"].includes(change.status);
  const needsClassification = finding.classification_gaps.length > 0;
  return <article className="review-finding-card">
    <div className="review-finding-top"><div><Badge tone={finding.finding_type === "qualifications" ? "amber" : "blue"}>{finding.finding_type.replaceAll("_", " ")}</Badge><Badge>{confidenceLabel(finding.confidence)}</Badge></div><Badge tone={statusTone(change?.status)}>{change?.status || finding.status}</Badge></div>
    <h3>{finding.candidate_name}</h3>
    <p className="review-claim">{finding.practical_capability || finding.technical_knowledge || finding.responsibilities || "No structured claim was extracted."}</p>
    <div className="review-tags">{finding.domains.map((domain) => <Badge key={domain.id}>{domain.name}</Badge>)}{finding.career_level && <Badge tone="violet">{finding.career_level.name}</Badge>}{finding.category && <Badge tone="blue">{finding.category.name}</Badge>}</div>
    {!locked && needsClassification && <div className="classification-warning"><strong>Manual classification needed</strong><span>Missing {finding.classification_gaps.map((gap) => gapLabels[gap] || gap).join(" · ")}</span></div>}
    <div className="evidence-list"><span className="source-label">Source evidence</span><blockquote>“{finding.evidence_excerpt || "No excerpt provided."}”</blockquote></div>
    <div className="review-card-actions"><button type="button" className="text-link" onClick={() => onInspect(finding)}>View comparison</button>{!locked && <><button type="button" className="button button-secondary" disabled={busy} onClick={() => onEdit(finding)}>{needsClassification ? "Resolve classification" : "Edit decision"}</button>{needsClassification ? <button type="button" className="button" disabled={busy} onClick={() => onEdit(finding)}>Complete fields to accept</button> : <button type="button" className="button" disabled={busy} onClick={() => onAccept(finding)}>Accept &amp; merge</button>}<button type="button" className="button button-danger" disabled={busy} onClick={() => onReject(finding)}>Reject</button></>}</div>
    {error && <div className="empty-state error-state" role="alert"><span className="state-icon">!</span><div><strong>Action failed</strong><p>{error.message}</p></div></div>}
    {children}
  </article>;
}

function EditPanel({ draft, domains, levels, categories, onChange, onSave, onSaveAndMerge, onCancel, busy }) {
  if (!draft) return null;
  return <section className="panel review-edit-panel"><div className="panel-title-row"><div><p className="eyebrow">EDIT PROPOSAL</p><h2>Review structured knowledge</h2></div><button type="button" className="text-link" onClick={onCancel}>Close</button></div><p className="muted-copy">Resolve classification gaps here before accepting. Changes are version checked and blank incoming values do not erase published knowledge.</p><div className="review-edit-grid"><label>Competency name<input value={draft.competency_name || ""} onChange={(event) => onChange("competency_name", event.target.value)} /></label><label>Security domains<select multiple value={(draft.domain_ids || []).map(String)} onChange={(event) => onChange("domain_ids", [...event.target.selectedOptions].map((option) => Number(option.value)))}>{domains.map((domain) => <option key={domain.id} value={domain.id}>{domain.parent_id ? `↳ ${domain.name}` : domain.name}</option>)}</select></label><label>Career level<select value={draft.career_level_id || ""} onChange={(event) => onChange("career_level_id", event.target.value ? Number(event.target.value) : null)}><option value="">Select a career level</option>{levels.map((level) => <option key={level.id} value={level.id}>{level.name}</option>)}</select></label><label>Competency category<select value={draft.category_id || ""} onChange={(event) => onChange("category_id", event.target.value ? Number(event.target.value) : null)}><option value="">Select a category</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label><label>Technical knowledge<textarea rows="3" value={draft.technical_knowledge || ""} onChange={(event) => onChange("technical_knowledge", event.target.value)} /></label><label>Practical capability<textarea rows="3" value={draft.practical_capability || ""} onChange={(event) => onChange("practical_capability", event.target.value)} /></label><label>Qualifications<textarea rows="2" value={draft.qualifications || ""} onChange={(event) => onChange("qualifications", event.target.value)} /></label><label>Tools and technologies<textarea rows="2" value={draft.tools_technologies || ""} onChange={(event) => onChange("tools_technologies", event.target.value)} /></label><label>Expectation description<textarea rows="3" value={draft.expectation_description || ""} onChange={(event) => onChange("expectation_description", event.target.value)} /></label><label>Reviewer note<textarea rows="2" value={draft.reviewer_note || ""} onChange={(event) => onChange("reviewer_note", event.target.value)} /></label></div><div className="review-card-actions"><button type="button" className="button button-secondary" onClick={onCancel}>Cancel</button><button type="button" className="button button-secondary" disabled={busy || !draft.expectation_description?.trim()} onClick={onSave}>Save reviewed proposal</button><button type="button" className="button" disabled={busy || !draft.expectation_description?.trim() || !draft.domain_ids?.length || !draft.career_level_id || !draft.category_id} onClick={onSaveAndMerge}>Save &amp; merge into domain</button></div></section>;
}

export default function ResearchReviewPage() {
  const [enteredKey, setEnteredKey] = useState(() => getAdminSessionKey());
  const [adminKey, setAdminKey] = useState(() => getAdminSessionKey());
  const [dashboard, setDashboard] = useState(null);
  const [filters, setFilters] = useState(emptyFilters);
  const [selectedSubmission, setSelectedSubmission] = useState(null);
  const [detail, setDetail] = useState(null);
  const [editing, setEditing] = useState(null);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);

  async function loadDashboard() {
    if (!adminKey) return;
    setLoading(true); setError(null);
    try { setDashboard(await fetchResearchReviewDashboard(filters, adminKey)); } catch (requestError) { setError(requestError); } finally { setLoading(false); }
  }
  useEffect(() => { if (adminKey) loadDashboard(); }, [adminKey, filters.domain_id, filters.subdomain_id, filters.career_level_id, filters.category_id, filters.source_id, filters.review_status, filters.change_type]);

  async function inspect(summary) {
    setSelectedSubmission(summary.id); setEditing(null); setError(null); setBusy(true);
    try { setDetail(await fetchResearchReviewSubmission(summary.id, adminKey)); } catch (requestError) { setError(requestError); } finally { setBusy(false); }
  }
  async function refreshDetail() { if (selectedSubmission) setDetail(await fetchResearchReviewSubmission(selectedSubmission, adminKey)); }
  async function mutate(action, finding, payload = {}) {
    const change = finding.review_change; if (!change) return;
    setBusy(true); setError(null); setActionError(null);
    try {
      let result;
      if (action === "accept") result = await acceptResearchReviewChange(change.id, change.version, payload.note, adminKey, true);
      if (action === "reject") result = await rejectResearchReviewChange(change.id, change.version, payload.note, adminKey);
      if (action === "modify" || action === "modify-merge") {
        result = await modifyResearchReviewChange(change.id, { ...payload, expected_version: change.version }, adminKey);
        if (action === "modify-merge") result = await acceptResearchReviewChange(change.id, result.change.version, payload.reviewer_note, adminKey, true);
      }
      if (result?.change) setDetail((current) => current ? { ...current, findings: current.findings.map((item) => item.id === finding.id ? { ...item, review_change: result.change } : item) } : current);
      setEditing(null); await Promise.all([loadDashboard(), refreshDetail()]);
    } catch (requestError) { setActionError({ findingId: finding.id, error: requestError }); await refreshDetail().catch(() => {}); } finally { setBusy(false); }
  }
  async function showPreview() { setBusy(true); setError(null); try { setPreview(await fetchResearchPublicationPreview(adminKey)); } catch (requestError) { setError(requestError); } finally { setBusy(false); } }
  async function publish() {
    if (!preview?.ready) return;
    setBusy(true); setError(null);
    try {
      const expected_versions = Object.fromEntries(preview.changes.map((change) => [change.id, change.version]));
      await publishResearchReview({ confirm: true, expected_versions }, adminKey); setPreview(null); await loadDashboard(); await refreshDetail();
    } catch (requestError) { setError(requestError); } finally { setBusy(false); }
  }

  function editedFields() {
    // Empty domain lists are omitted so the backend keeps the current proposal instead of rejecting the request.
    return { competency_name: editing.competency_name, domain_ids: editing.domain_ids?.length ? editing.domain_ids : undefined, career_level_id: editing.career_level_id, category_id: editing.category_id, technical_knowledge: editing.technical_knowledge, practical_capability: editing.practical_capability, qualifications: editing.qualifications, tools_technologies: editing.tools_technologies, expectation_description: editing.expectation_description, reviewer_note: editing.reviewer_note };
  }
  function renderPanel() {
    if (editing.mode === "comparison") return <section className="panel comparison-panel"><div className="panel-title-row"><div><p className="eyebrow">PROPOSED KNOWLEDGE CHANGE</p><h2>{editing.finding.candidate_name}</h2></div><button className="text-link" onClick={() => setEditing(null)}>Close</button></div><ChangeSummary change={editing.finding.review_change} /><div className="comparison-columns"><div><span className="source-label">Incoming evidence</span><blockquote>“{editing.finding.evidence_excerpt || "No excerpt"}”</blockquote><p>{editing.finding.technical_knowledge || editing.finding.practical_capability || "No structured field supplied."}</p></div><div><span className="source-label">Proposed update</span><p><strong>{editing.finding.review_change.proposed.expectation_description || "No expectation description"}</strong></p><p>{editing.finding.review_change.proposed.practical_capability || editing.finding.review_change.proposed.technical_knowledge || "No proposed structured capability."}</p></div></div></section>;
    return <EditPanel draft={editing} domains={filterOptions.domains} levels={filterOptions.career_levels} categories={filterOptions.categories} busy={busy} onCancel={() => setEditing(null)} onChange={(field, value) => setEditing({ ...editing, [field]: value })} onSave={() => mutate("modify", editing.finding, editedFields())} onSaveAndMerge={() => mutate("modify-merge", editing.finding, editedFields())} />;
  }

  const filterOptions = dashboard?.filters || { domains: [], career_levels: [], categories: [], sources: [] };
  const domainOptions = useMemo(() => filterOptions.domains.filter((item) => !item.parent_id), [filterOptions.domains]);
  if (!adminKey) return <><PageHeader eyebrow="PHASE 5 / RESEARCH REVIEW" title="Research Review" description="Inspect imported findings, verify evidence and classification, and publish approved knowledge-base changes atomically." /><section className="panel research-auth"><p className="eyebrow">ADMINISTRATOR ACCESS</p><h2>Unlock research review</h2><p className="muted-copy">The administrator key is used only for this browser session and is cleared when you lock the workspace or close the browser session.</p><input aria-label="Administrator API key" type="password" placeholder="X-Admin-API-Key" value={enteredKey} onChange={(event) => setEnteredKey(event.target.value)} /><button className="button" disabled={!enteredKey} onClick={() => { setAdminSessionKey(enteredKey); setAdminKey(enteredKey); }}>Open review workspace</button></section></>;

  return <>
    <PageHeader eyebrow="PHASE 5 / RESEARCH REVIEW" title="Research Review" description="Inspect imported findings, compare proposed changes with the knowledge base, and publish administrator-approved updates with an audit trail."><div className="review-card-actions"><button className="button" disabled={busy} onClick={showPreview}>Review publication batch</button><button className="button button-secondary" onClick={() => { clearAdminSessionKey(); setAdminKey(""); setEnteredKey(""); setDashboard(null); setDetail(null); }}>Lock workspace</button></div></PageHeader>
    {error && <ErrorState error={error} onRetry={loadDashboard} />}
    <section className="stats-grid review-stats"><article className="stat-card"><span>Pending submissions</span><strong>{dashboard?.pending_reviews.length || 0}</strong><small>Awaiting administrator review</small></article><article className="stat-card stat-blue"><span>Approved changes</span><strong>{dashboard?.approved_changes.length || 0}</strong><small>Ready for publication</small></article><article className="stat-card stat-violet"><span>Rejected findings</span><strong>{dashboard?.rejected_findings.length || 0}</strong><small>Retained for auditability</small></article><article className="stat-card stat-amber"><span>Published history</span><strong>{dashboard?.change_history.length || 0}</strong><small>Previously published proposals</small></article></section>
    <section className="panel review-filter-panel"><div className="panel-title-row"><div><p className="eyebrow">REVIEW QUEUE</p><h2>Filter imported findings</h2></div>{loading && <Loading label="Refreshing" />}</div><div className="review-filters"><label>Domain<select value={filters.domain_id} onChange={(event) => setFilters({ ...filters, domain_id: event.target.value, subdomain_id: "" })}><option value="">All domains</option>{domainOptions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Career level<select value={filters.career_level_id} onChange={(event) => setFilters({ ...filters, career_level_id: event.target.value })}><option value="">All levels</option>{filterOptions.career_levels.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Category<select value={filters.category_id} onChange={(event) => setFilters({ ...filters, category_id: event.target.value })}><option value="">All categories</option>{filterOptions.categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Status<select value={filters.review_status} onChange={(event) => setFilters({ ...filters, review_status: event.target.value })}><option value="">All statuses</option><option value="pending">Pending</option><option value="accepted">Accepted</option><option value="modified">Modified</option><option value="merged">Merged</option><option value="rejected">Rejected</option><option value="published">Published</option></select></label></div></section>
    <div className="review-workspace"><section className="panel review-submissions"><div className="panel-title-row"><div><p className="eyebrow">IMPORTED SOURCES</p><h2>Pending review</h2></div><Badge>{dashboard?.pending_reviews.length || 0}</Badge></div>{dashboard?.pending_reviews.length ? dashboard.pending_reviews.map((summary) => <button className={`review-submission-row ${selectedSubmission === summary.id ? "selected" : ""}`} key={summary.id} onClick={() => inspect(summary)}><span className="pulse" /><span><strong>{summary.source_title}</strong><small>{summary.source_type} · {summary.finding_count} findings · {summary.proposed_new_competencies} new · {summary.proposed_updates} updates</small></span><b>→</b></button>) : <EmptyState title="No pending submissions" message="Imported findings will appear here after extraction." />}</section>
      <section className="review-detail-column">{busy && !detail ? <section className="panel"><Loading label="Loading findings" /></section> : detail ? <><section className="panel review-source-panel"><div className="panel-title-row"><div><p className="eyebrow">SOURCE / {detail.source.type}</p><h2>{detail.source.title}</h2><p className="muted-copy">{detail.source.url} · Provider {detail.source.provider || "unknown"} · Model {detail.source.model_name || detail.source.model_id || "unknown"}</p></div><Badge tone={statusTone(detail.submission.review_status)}>{detail.submission.review_status}</Badge></div><div className="review-source-meta"><span>Submitted {new Date(detail.submission.submitted_at).toLocaleString()}</span><span>{detail.submission.finding_count} extracted findings</span><span>{detail.domain_impact.length} affected domains</span></div></section><section className="review-impact-grid">{detail.domain_impact.map((impact) => <article className="panel impact-card" key={impact.domain.id}><p className="eyebrow">DOMAIN IMPACT</p><h3>{impact.domain.name}</h3><strong>{impact.change_count} proposed changes</strong><span>{impact.career_levels.join(" · ") || "Career level pending"}</span><small>{impact.new_competencies.length} new competencies · {impact.modified_competencies.length} modified · {impact.evidence_changes} evidence links</small></article>)}</section><div className="review-findings">{detail.findings.map((finding) => <FindingCard key={finding.id} finding={finding} busy={busy} onInspect={(item) => setEditing({ mode: "comparison", finding: item })} onEdit={(item) => setEditing({ mode: "edit", finding: item, ...item.review_change.proposed, reviewer_note: "" })} onAccept={(item) => mutate("accept", item)} onReject={(item) => mutate("reject", item)} error={actionError?.findingId === finding.id ? actionError.error : null}>{editing?.finding.id === finding.id && renderPanel()}</FindingCard>)}</div></> : <section className="panel"><EmptyState title="Select an imported source" message="Choose a submission to inspect proposed changes, evidence, confidence, classification gaps, and domain impact." /></section>}
      </section>
    </div>
    {preview && <div className="review-modal-backdrop"><section className="panel review-modal"><div className="panel-title-row"><div><p className="eyebrow">ATOMIC PUBLICATION</p><h2>Confirm knowledge-base changes</h2></div><button className="text-link" onClick={() => setPreview(null)}>Close</button></div><p className="muted-copy">This batch publishes all approved changes together. If any validation fails, no knowledge-base row is changed.</p><div className="publication-summary"><strong>{preview.new_competencies}</strong><span>new competencies</span><strong>{preview.updated_expectations}</strong><span>updated expectations</span><strong>{preview.merged_findings}</strong><span>merged findings</span></div><div className="review-tags">{preview.affected_domains.map((domain) => <Badge key={domain.id}>{domain.name} · {domain.change_count} changes</Badge>)}</div>{preview.blockers.length > 0 && <div className="classification-warning"><strong>Publication blocked</strong>{preview.blockers.map((blocker) => <span key={blocker}>{blocker}</span>)}</div>}<div className="review-card-actions"><button className="button button-secondary" onClick={() => setPreview(null)}>Cancel</button><button className="button" disabled={busy || !preview.ready} onClick={publish}>Publish approved batch</button></div></section></div>}
  </>;
}
