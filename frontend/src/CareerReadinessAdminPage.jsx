import { useEffect, useMemo, useState } from "react";

import {
  clearAdminSessionKey,
  createKnowledgeTopic,
  fetchKnowledgeTopicAdmin,
  fetchKnowledgeTopicHistory,
  fetchKnowledgeTopicProposals,
  mergeKnowledgeTopic,
  getAdminSessionKey,
  publishKnowledgeTopic,
  publishKnowledgeTopicProposals,
  reviewKnowledgeTopicProposal,
  setAdminSessionKey,
  setKnowledgeTopicActive,
  updateKnowledgeTopic,
} from "./api";
import { Badge, EmptyState, ErrorState, Loading, PageHeader } from "./components";
import KnowledgeSectionEditor from "./KnowledgeSectionEditor";

const emptyForm = { name: "", description: "", category_id: "", domain_ids: [], industry_ids: [], aliases: "", level_expectations: [] };

function formPayload(form) {
  return { name: form.name.trim(), description: form.description.trim(), category_id: form.category_id ? Number(form.category_id) : null, domain_ids: form.domain_ids, industry_ids: form.industry_ids, aliases: form.aliases.split(",").map((item) => item.trim()).filter(Boolean), level_expectations: form.level_expectations || [] };
}
function proposalDraft(proposal, overrides = {}) {
  return { ...proposal.proposed, ...overrides, name: (overrides.name ?? proposal.proposed.name ?? "").trim(), description: overrides.description ?? proposal.proposed.description ?? "", domain_ids: proposal.proposed.domain_ids || [], industry_ids: proposal.proposed.industry_ids || [], aliases: proposal.proposed.aliases || [], related_competency_ids: proposal.proposed.related_competency_ids || [], level_expectations: proposal.proposed.level_expectations || [] };
}

export default function CareerReadinessAdminPage({ initialTab = "review" }) {
  const [enteredKey, setEnteredKey] = useState(() => getAdminSessionKey());
  const [adminKey, setAdminKey] = useState(() => getAdminSessionKey());
  const [tab, setTab] = useState(initialTab);
  const [topics, setTopics] = useState([]);
  const [proposals, setProposals] = useState([]);
  const [filters, setFilters] = useState({ status_filter: "review", proposal_type: "" });
  const [options, setOptions] = useState({ domains: [], industries: [], career_levels: [], categories: [] });
  const [form, setForm] = useState(emptyForm);
  const [editingTopic, setEditingTopic] = useState(null);
  const [proposalEdits, setProposalEdits] = useState({});
  const [historyItems, setHistoryItems] = useState(null);
  const [sectionTopic, setSectionTopic] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  async function load() {
    if (!adminKey) return;
    setLoading(true); setError(null);
    try {
      const [topicRows, proposalPage] = await Promise.all([fetchKnowledgeTopicAdmin({ include_inactive: true }, adminKey), fetchKnowledgeTopicProposals(filters, adminKey)]);
      setTopics(topicRows); setProposals(proposalPage.items); setOptions(proposalPage.filters);
    } catch (requestError) { setError(requestError); } finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [adminKey, filters.status_filter, filters.proposal_type]);

  const approved = useMemo(() => proposals.filter((item) => item.status === "approved"), [proposals]);
  function unlock() { if (enteredKey.trim()) { setAdminSessionKey(enteredKey.trim()); setAdminKey(enteredKey.trim()); } }
  function lock() { clearAdminSessionKey(); setAdminKey(""); setEnteredKey(""); }
  async function act(action, proposal, extra = {}) {
    setSaving(true); setError(null); setNotice(null);
    try { await reviewKnowledgeTopicProposal(proposal.id, { expected_version: proposal.version, action, reviewer_note: extra.reviewer_note || "", ...(action === "modify" ? { proposal: proposalDraft(proposal, extra) } : {}), ...(action === "merge" ? { target_topic_id: Number(extra.target_topic_id) } : {}) }, adminKey); setNotice(`Proposal ${action}d and retained in the review history.`); await load(); }
    catch (requestError) { setError(requestError); } finally { setSaving(false); }
  }
  async function publishProposals() {
    setSaving(true); setError(null);
    try { await publishKnowledgeTopicProposals({ confirm: true, proposal_ids: approved.map((item) => item.id), expected_versions: Object.fromEntries(approved.map((item) => [item.id, item.version])), change_reason: "Administrator approved Career Readiness proposal." }, adminKey); setNotice("Approved Career Readiness changes published."); await load(); }
    catch (requestError) { setError(requestError); } finally { setSaving(false); }
  }
  async function saveTopic(event) {
    event.preventDefault(); setSaving(true); setError(null);
    try {
      const payload = formPayload(form);
      if (editingTopic) {
        const updated = await updateKnowledgeTopic(editingTopic.id, { expected_version: editingTopic.version, ...payload, change_reason: "Administrator edited Career Readiness topic." }, adminKey);
        setNotice("Topic saved as a reviewed draft. Publish it explicitly when ready.");
        setEditingTopic(updated);
      } else {
        const created = await createKnowledgeTopic(payload, adminKey);
        setNotice("Topic created as a draft. Publish it explicitly when ready.");
        setEditingTopic(created);
      }
      setForm(emptyForm); await load();
    } catch (requestError) { setError(requestError); } finally { setSaving(false); }
  }
  async function publishTopic(topic) {
    setSaving(true); setError(null);
    try { await publishKnowledgeTopic(topic.id, { confirm: true, expected_versions: { [topic.id]: topic.version }, change_reason: "Administrator published manual topic change." }, adminKey); setNotice(`${topic.name} is now published.`); await load(); }
    catch (requestError) { setError(requestError); } finally { setSaving(false); }
  }
  async function toggleTopic(topic) {
    setSaving(true); setError(null);
    try { await setKnowledgeTopicActive(topic.id, !topic.is_active, adminKey); setNotice(`${topic.name} ${topic.is_active ? "deactivated" : "reactivated"}.`); await load(); }
    catch (requestError) { setError(requestError); } finally { setSaving(false); }
  }
  async function mergeTopic(topic) {
    const targetId = window.prompt(`Merge ${topic.name} into topic ID:`);
    if (!targetId || !Number(targetId)) return;
    setSaving(true); setError(null);
    try { await mergeKnowledgeTopic(topic.id, Number(targetId), "Administrator merged duplicate knowledge topics.", adminKey); setNotice(`${topic.name} was merged and deactivated.`); await load(); }
    catch (requestError) { setError(requestError); } finally { setSaving(false); }
  }

  async function showHistory(topic) {
    try { setHistoryItems({ topic, data: await fetchKnowledgeTopicHistory(topic.id, adminKey) }); } catch (requestError) { setError(requestError); }
  }
  function startEdit(topic) {
    setEditingTopic(topic);
    setForm({ name: topic.name, description: topic.description, category_id: topic.category?.id || "", domain_ids: topic.domains.map((item) => item.id), industry_ids: topic.industries.map((item) => item.id), aliases: topic.aliases.join(", "), level_expectations: topic.level_expectations.map((item) => ({ career_level_id: item.career_level?.id, industry_id: item.industry?.id || null, expectation: item.expectation, practical_capability: item.practical_capability, display_order: item.display_order || 0 })) });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  if (!adminKey) return <><PageHeader eyebrow="RESEARCH ADMIN / CAREER READINESS" title="Career Readiness administration" description="Review research-derived knowledge proposals and maintain the published checklist." /><section className="panel research-auth"><p className="eyebrow">ADMINISTRATOR ACCESS</p><h2>Unlock Career Readiness administration</h2><p className="muted-copy">All AI-generated additions and updates remain unpublished until an administrator reviews and explicitly publishes them.</p><input aria-label="Administrator API key" type="password" placeholder="X-Admin-API-Key" value={enteredKey} onChange={(event) => setEnteredKey(event.target.value)} /><button className="button" disabled={!enteredKey.trim()} onClick={unlock}>Open Career Readiness workspace</button></section></>;

  return <>
    <PageHeader eyebrow="RESEARCH ADMIN / CAREER READINESS" title={tab === "review" ? "Career Readiness Review" : "Knowledge Topic Management"} description="Maintain a reviewed, evidence-backed cybersecurity knowledge checklist. Research proposals never publish automatically."><div className="review-card-actions"><button className="button button-secondary" onClick={load} disabled={loading}>Refresh</button><button className="button button-secondary" onClick={lock}>Lock workspace</button></div></PageHeader>
    {error && <ErrorState error={error} onRetry={load} />}{notice && <p className="success-copy" role="status">{notice}</p>}
    <div className="admin-tabs" role="tablist"><button role="tab" aria-selected={tab === "review"} className={tab === "review" ? "active" : ""} onClick={() => setTab("review")}>Career Readiness Review <Badge tone="amber">{proposals.filter((item) => ["review", "deferred"].includes(item.status)).length}</Badge></button><button role="tab" aria-selected={tab === "topics"} className={tab === "topics" ? "active" : ""} onClick={() => setTab("topics")}>Knowledge Topic Management <Badge>{topics.length}</Badge></button></div>
    {tab === "review" ? <ReviewTab proposals={proposals} approved={approved} filters={filters} setFilters={setFilters} saving={saving} edits={proposalEdits} setEdits={setProposalEdits} act={act} publishProposals={publishProposals} /> : <TopicsTab topics={topics} options={options} form={form} setForm={setForm} editingTopic={editingTopic} setEditingTopic={setEditingTopic} saveTopic={saveTopic} startEdit={startEdit} publishTopic={publishTopic} toggleTopic={toggleTopic} mergeTopic={mergeTopic} showHistory={showHistory} saving={saving} historyItems={historyItems} setHistoryItems={setHistoryItems} onEditSections={setSectionTopic} />}
    {sectionTopic && <KnowledgeSectionEditor topic={sectionTopic} adminKey={adminKey} onClose={() => setSectionTopic(null)} onSaved={() => { setSectionTopic(null); load(); }} />}
  </>;
}

function ReviewTab({ proposals, approved, filters, setFilters, saving, edits, setEdits, act, publishProposals }) {
  return <><section className="panel review-filter-panel"><div className="panel-title-row"><div><p className="eyebrow">PROPOSAL QUEUE</p><h2>Research-derived topic changes</h2><p className="muted-copy">Inspect evidence, AI interpretation, confidence, and exact proposed content before approval.</p></div><button className="button" disabled={saving || !approved.length} onClick={publishProposals}>Publish approved ({approved.length})</button></div><div className="review-filters"><label>Status<select value={filters.status_filter} onChange={(event) => setFilters({ ...filters, status_filter: event.target.value })}><option value="">All statuses</option><option value="review">Review</option><option value="approved">Approved</option><option value="published">Published</option><option value="rejected">Rejected</option><option value="deferred">Deferred</option></select></label><label>Proposal type<select value={filters.proposal_type} onChange={(event) => setFilters({ ...filters, proposal_type: event.target.value })}><option value="">All proposal types</option><option value="new_topic">New topic</option><option value="topic_update">Topic update</option><option value="evidence_update">Evidence update</option></select></label></div></section><div className="topic-proposal-list">{proposals.length ? proposals.map((proposal) => <ProposalCard key={proposal.id} proposal={proposal} saving={saving} edits={edits} setEdits={setEdits} act={act} />) : <section className="panel"><EmptyState title="No topic proposals" message="Analyzed research findings will appear here after topic mapping." /></section>}</div></>;
}

function ProposalCard({ proposal, saving, edits, setEdits, act }) {
  const proposed = proposal.proposed || {};
  const edit = edits[proposal.id] || { name: proposed.name || "", description: proposed.description || "" };
  const canReview = ["review", "deferred"].includes(proposal.status);
  return <article className="panel topic-proposal-card"><div className="proposal-heading"><div><Badge tone={proposal.proposal_type === "new_topic" ? "violet" : "blue"}>{proposal.proposal_type.replaceAll("_", " ")}</Badge><h2>{proposed.name || "Unnamed topic"}</h2><p className="muted-copy">Proposal #{proposal.id} · version {proposal.version} · evidence: {proposal.evidence_status} · confidence {proposal.confidence == null ? "not supplied" : `${Math.round(proposal.confidence * 100)}%`}</p></div><Badge tone={proposal.status === "approved" ? "mint" : proposal.status === "rejected" ? "rose" : "amber"}>{proposal.status}</Badge></div><div className="topic-proposal-grid"><div><span className="field-label">Current published content</span>{proposal.original ? <pre>{JSON.stringify(proposal.original, null, 2)}</pre> : <p className="muted-copy">No published topic exists; this is a proposed new topic.</p>}</div><div><span className="field-label">Proposed content</span>{canReview ? <><label>Topic name<input value={edit.name} onChange={(event) => setEdits({ ...edits, [proposal.id]: { ...edit, name: event.target.value } })} /></label><label>Description<textarea rows="3" value={edit.description} onChange={(event) => setEdits({ ...edits, [proposal.id]: { ...edit, description: event.target.value } })} /></label></> : <pre>{JSON.stringify(proposed, null, 2)}</pre>}</div></div><p><strong>AI interpretation:</strong> {proposal.ai_interpretation || "No AI interpretation retained."}</p><div className="topic-proposal-evidence"><strong>Supporting research</strong>{proposal.source_references?.length ? proposal.source_references.map((item, index) => <blockquote key={`${item.source_id}-${index}`}>“{item.excerpt}” <small>{item.source_title} · <a href={item.source_url} target="_blank" rel="noreferrer">source ↗</a></small></blockquote>) : <p className="muted-copy">No excerpts were retained.</p>}</div>{proposal.potential_duplicates?.length ? <p className="warning-copy"><strong>Potential duplicates:</strong> {proposal.potential_duplicates.map((item) => item.name).join(", ")}</p> : null}<div className="review-card-actions">{canReview && <><button className="button" disabled={saving} onClick={() => act("modify", proposal, edit)}>Modify proposal</button><button className="button button-secondary" disabled={saving} onClick={() => act("accept", proposal)}>Accept</button><button className="button button-secondary" disabled={saving} onClick={() => act("defer", proposal)}>Defer</button><button className="button button-danger" disabled={saving} onClick={() => act("reject", proposal)}>Reject</button></>}{proposal.status === "approved" && <span className="muted-copy">Approved; select Publish approved above to expose it publicly.</span>}</div></article>;
}

function TopicsTab({ topics, options, form, setForm, editingTopic, setEditingTopic, saveTopic, startEdit, publishTopic, toggleTopic, mergeTopic, showHistory, saving, historyItems, setHistoryItems, onEditSections }) {
  function setField(key, value) { setForm({ ...form, [key]: value }); }
  return <><section className="panel topic-editor"><div className="panel-title-row"><div><p className="eyebrow">{editingTopic ? "EDIT TOPIC" : "ADD TOPIC"}</p><h2>{editingTopic ? `Edit ${editingTopic.name}` : "Create a canonical knowledge topic"}</h2></div>{editingTopic && <button className="text-link" onClick={() => { setEditingTopic(null); setForm(emptyForm); }}>Cancel edit</button>}</div><form className="topic-editor-form" onSubmit={saveTopic}><label>Name<input required value={form.name} onChange={(event) => setField("name", event.target.value)} placeholder="IDOR / BOLA" /></label><label>Description<textarea required rows="3" value={form.description} onChange={(event) => setField("description", event.target.value)} placeholder="Object-level authorization weaknesses…" /></label><label>Category<select value={form.category_id} onChange={(event) => setField("category_id", event.target.value)}><option value="">Select category</option>{options.categories?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Aliases<input value={form.aliases} onChange={(event) => setField("aliases", event.target.value)} placeholder="BOLA, object-level authorization" /></label><label>Domains<select multiple value={form.domain_ids.map(String)} onChange={(event) => setField("domain_ids", [...event.target.selectedOptions].map((option) => Number(option.value)))}>{options.domains?.map((item) => <option key={item.id} value={item.id}>{item.parent_id ? `↳ ${item.name}` : item.name}</option>)}</select></label><label>Industries<select multiple value={form.industry_ids.map(String)} onChange={(event) => setField("industry_ids", [...event.target.selectedOptions].map((option) => Number(option.value)))}>{options.industries?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button className="button" disabled={saving}>{editingTopic ? "Save reviewed draft" : "Add topic as draft"}</button></form></section><section className="panel"><div className="panel-title-row"><div><p className="eyebrow">CANONICAL TOPICS</p><h2>Published and draft knowledge</h2></div><Badge>{topics.length}</Badge></div>{topics.length ? <div className="topic-management-list">{topics.map((topic) => <article className={`topic-management-row ${topic.is_active ? "" : "inactive"}`} key={topic.id}><div><div><Badge tone={topic.publication_status === "published" ? "mint" : "amber"}>{topic.publication_status}</Badge><Badge>v{topic.version}</Badge></div><h3>{topic.name}</h3><p>{topic.description}</p><small>{topic.domains.map((item) => item.name).join(" · ") || "No domain mapping"} · {topic.evidence_count} evidence items</small></div><div className="review-card-actions"><button className="button button-secondary" onClick={() => startEdit(topic)}>Edit</button>{topic.publication_status !== "published" && <button className="button" disabled={saving} onClick={() => publishTopic(topic)}>Publish</button>}<button className="button button-secondary" disabled={saving} onClick={() => toggleTopic(topic)}>{topic.is_active ? "Deactivate" : "Reactivate"}</button>{topic.is_active && <button className="button button-secondary" disabled={saving} onClick={() => mergeTopic(topic)}>Merge</button>}<button className="button button-secondary" onClick={() => onEditSections(topic)}>Edit sections</button><button className="text-link" onClick={() => showHistory(topic)}>History</button></div></article>)}</div> : <EmptyState title="No topics yet" message="Create the first canonical knowledge topic above." />}</section>{historyItems && <div className="review-modal-backdrop" role="presentation"><section className="panel review-modal" role="dialog" aria-modal="true"><div className="panel-title-row"><h2>History: {historyItems.topic.name}</h2><button className="text-link" onClick={() => setHistoryItems(null)}>Close</button></div><div className="topic-history-list">{historyItems.data.items.map((item) => <article key={`${item.kind}-${item.id}`}><Badge>{item.kind === "version" ? `Version ${item.version}` : item.action}</Badge><span>{item.actor} · {new Date(item.created_at).toLocaleString()}</span><p>{item.reason}</p><pre>{JSON.stringify(item.snapshot || item.after || {}, null, 2)}</pre></article>)}</div></section></div>}</>;
}
