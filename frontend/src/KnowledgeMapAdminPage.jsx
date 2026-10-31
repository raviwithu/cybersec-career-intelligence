import { useCallback, useEffect, useMemo, useState } from "react";

import { clearAdminSessionKey, createKnowledgeProposal, createTaxonomyEntry, deleteTaxonomyEntry, fetchDomains, fetchIndustries, fetchKnowledgeAdminTopics, fetchKnowledgeContractHistory, fetchKnowledgeMapBranchTopics, fetchKnowledgeReviewQueue, fetchLevels, getAdminSessionKey, setAdminSessionKey, setTaxonomyActive, updateTaxonomyEntry } from "./api";
import { Badge, EmptyState, ErrorState, Loading, PageHeader } from "./components";
import KnowledgeMapPage from "./KnowledgeMapPage";
import KnowledgeMapSuggestions from "./KnowledgeMapSuggestions";
import KnowledgeSectionEditor from "./KnowledgeSectionEditor";
import { MAP_ACTION_LABELS } from "./knowledgeMapActions";
import { BRANCHES, ROOT_ID, branchNodeId, domainNodeId } from "./knowledgeMapModel";

// Knowledge Map Management: administrators propose map changes here. Every topic form creates a knowledge-contract
// proposal that is reviewed and published in Knowledge Review; only "Add sub-domain" saves taxonomy directly.

const OPEN_STATUSES = new Set(["draft", "review", "deferred", "approved"]);
const RELATIONSHIP_TYPES = [["prerequisite", "Prerequisite"], ["related", "Related"], ["specialization", "Specialization"], ["dependency", "Depends on"], ["mitigated_by", "Mitigated by"], ["tested_by", "Tested by"]];
const BRANCH_OPTIONS = Object.entries(BRANCHES).map(([id, branch]) => [id, branch.label]);

const normal = (value) => String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "");

// Exact matches use the backend's duplicate rule (normalised name, slug, key, aliases); similar ones are hints only.
export function possibleDuplicates(topics, name) {
  const wanted = normal(name);
  if (wanted.length < 3) return [];
  return topics.map((topic) => {
    const names = [topic.name, topic.slug, topic.topic_key, ...(topic.aliases || [])].map(normal).filter(Boolean);
    if (names.includes(wanted)) return { topic, exact: true };
    if (wanted.length >= 4 && names.some((value) => value.includes(wanted) || wanted.includes(value))) return { topic, exact: false };
    return null;
  }).filter(Boolean).sort((a, b) => Number(b.exact) - Number(a.exact)).slice(0, 6);
}

// Which topics and branches have open map proposals. Read from proposals, never from live data.
export function pendingIndex(proposals) {
  const topics = new Map();
  const branches = new Set();
  proposals.filter((item) => OPEN_STATUSES.has(item.status)).forEach((item) => {
    if (item.topic_id) topics.set(item.topic_id, [...(topics.get(item.topic_id) || []), item]);
    const content = item.proposed_content || {};
    const targets = [content, content.to, ...(content.placements || [])].filter((target) => target?.domain_id && target.map_branch);
    targets.forEach((target) => branches.add(branchNodeId(target.domain_id, target.map_branch)));
  });
  return { topics, branches };
}

// GET /domains nests children under their parents; the page works with one flat list of every level.
export function flattenDomains(domains) {
  return domains.flatMap(({ children = [], ...domain }) => [domain, ...flattenDomains(children)]);
}

// Domains in tree order (each child right under its parent, any depth), with depth and the full path for labels.
export function domainTree(domains) {
  const known = new Set(domains.map((domain) => domain.id));
  const byParent = new Map();
  domains.forEach((domain) => {
    const parent = known.has(domain.parent_id) ? domain.parent_id : null;
    byParent.set(parent, [...(byParent.get(parent) || []), domain]);
  });
  const result = [];
  const seen = new Set();
  function visit(parentId, depth, path) {
    (byParent.get(parentId) || []).sort((a, b) => (a.display_order ?? 0) - (b.display_order ?? 0) || a.name.localeCompare(b.name)).forEach((domain) => {
      if (seen.has(domain.id)) return;
      seen.add(domain.id);
      const domainPath = [...path, domain.name];
      result.push({ ...domain, depth, path: domainPath });
      visit(domain.id, depth + 1, domainPath);
    });
  }
  visit(null, 0, []);
  return result;
}

function DomainSelect({ domains, value, onChange, label = "Domain", emptyLabel = "Choose a domain" }) {
  return <label>{label}<select value={value} onChange={(event) => onChange(event.target.value)}><option value="">{emptyLabel}</option>{domainTree(domains).map((domain) => <option key={domain.id} value={domain.id}>{"   ".repeat(domain.depth)}{domain.depth ? "↳ " : ""}{domain.name}</option>)}</select></label>;
}

// Adds a child domain under the selected domain, at any depth. Domains are taxonomy, not knowledge content, so this
// saves immediately through the Taxonomy Management API (same as adding it there); topic changes still need review.
function SubDomainForm({ parent, domains, adminKey, onCreated }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState("");
  const path = domainTree(domains).find((domain) => domain.id === parent.domainId)?.path || [parent.label];
  async function submit(event) {
    event.preventDefault();
    setError(null); setNotice("");
    if (!name.trim()) { setError(new Error("A sub-domain name is required.")); return; }
    setBusy(true);
    try {
      const created = await createTaxonomyEntry("domain", { name: name.trim(), description: description.trim(), parent_id: parent.domainId }, adminKey);
      setNotice(`${created.name} was added under ${path.join(" › ")}. Place topics in its Foundations, Security or Common Vulnerabilities branch, or add another level under it.`);
      setName(""); setDescription("");
      await onCreated?.(created);
    } catch (requestError) { setError(requestError); } finally { setBusy(false); }
  }
  return <form className="kma-form" onSubmit={submit} aria-label="Add sub-domain">
    <h3>Add sub-domain</h3>
    <p className="muted-copy">Adds a child domain under {path.join(" › ")}. It is saved immediately, like in Taxonomy Management; select the new sub-domain to add further levels under it.</p>
    <label>Sub-domain name<input value={name} maxLength="180" onChange={(event) => setName(event.target.value)} /></label>
    <label>Description<textarea rows="2" maxLength="4000" value={description} onChange={(event) => setDescription(event.target.value)} /></label>
    {error && <p className="kma-error" role="alert">{error.message}</p>}
    {notice && <p className="success-copy" role="status">{notice}</p>}
    <button type="submit" className="button" disabled={busy}>{busy ? "Adding…" : "Add sub-domain"}</button>
  </form>;
}

function BranchSelect({ value, onChange }) {
  return <label>Branch<select value={value} onChange={(event) => onChange(event.target.value)}>{BRANCH_OPTIONS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>;
}

function TopicSelect({ topics, value, onChange, exclude, label = "Topic", allowNone = false }) {
  const [filter, setFilter] = useState("");
  const options = topics.filter((topic) => topic.id !== exclude && (!filter || normal(topic.name).includes(normal(filter)) || topic.id === Number(value)));
  return <div className="kma-topic-select">
    <label>{label} filter<input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Type to narrow the list" /></label>
    <label>{label}<select value={value} onChange={(event) => onChange(event.target.value)}><option value="">{allowNone ? "No parent (top level)" : "Choose a topic"}</option>{options.map((topic) => <option key={topic.id} value={topic.id}>{topic.name}</option>)}</select></label>
  </div>;
}

function ChildDomainWarning({ domains, domainId }) {
  const children = domains.filter((domain) => domain.parent_id === Number(domainId));
  if (!children.length) return null;
  return <p className="kma-warning" role="note">⚠ This domain has child domains ({children.map((domain) => domain.name).join(", ")}). Consider placing the topic in the most specific child domain instead.</p>;
}

// One proposal form: fields come from the caller; build() returns { action, topic_id?, proposed_content, ... } or an error string.
function ProposalForm({ title, adminKey, build, onSubmitted, children, submitLabel = "Submit for review" }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState("");
  async function submit(event) {
    event.preventDefault();
    setError(null); setNotice("");
    const built = build();
    if (typeof built === "string") { setError(new Error(built)); return; }
    if (!reason.trim()) { setError(new Error("A change reason is required.")); return; }
    setBusy(true);
    try {
      const result = await createKnowledgeProposal({ schema_version: "1.0", source_type: "manual", submit_for_review: true, change_reason: reason.trim(), references: [], ...built }, adminKey, `map-${built.action}-${Date.now()}`);
      setNotice(`Proposal #${result.id} submitted for review. Live data changes only after it is approved and published in Knowledge Review.`);
      setReason("");
      onSubmitted?.(result);
    } catch (requestError) { setError(requestError); } finally { setBusy(false); }
  }
  return <form className="kma-form" onSubmit={submit} aria-label={title}>
    <h3>{title}</h3>
    {children}
    <label>Change reason<textarea rows="2" maxLength="500" value={reason} onChange={(event) => setReason(event.target.value)} aria-required="true" /></label>
    {error && <p className="kma-error" role="alert">{error.message}</p>}
    {notice && <p className="success-copy" role="status">{notice}</p>}
    <button type="submit" className="button" disabled={busy}>{busy ? "Submitting…" : submitLabel}</button>
  </form>;
}

function PlaceForm({ topics, domains, adminKey, onSubmitted, fixedTopicId, fixedDomainId, fixedBranch }) {
  const [topicId, setTopicId] = useState(fixedTopicId ? String(fixedTopicId) : "");
  const [domainId, setDomainId] = useState(fixedDomainId ? String(fixedDomainId) : "");
  const [branch, setBranch] = useState(fixedBranch || "foundations");
  return <ProposalForm title="Place topic" adminKey={adminKey} onSubmitted={onSubmitted} build={() => (!topicId || !domainId ? "Choose a topic and a domain." : { action: "PLACE_TOPIC", topic_id: Number(topicId), proposed_content: { domain_id: Number(domainId), map_branch: branch } })}>
    {!fixedTopicId && <TopicSelect topics={topics} value={topicId} onChange={setTopicId} />}
    {!fixedDomainId && <DomainSelect domains={domains} value={domainId} onChange={setDomainId} />}
    {!fixedBranch && <BranchSelect value={branch} onChange={setBranch} />}
    <ChildDomainWarning domains={domains} domainId={domainId} />
  </ProposalForm>;
}

function ReorderForm({ node, adminKey, onSubmitted }) {
  const [members, setMembers] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let active = true;
    (async () => {
      const items = [];
      for (let offset = 0; ; offset += 100) {
        const page = await fetchKnowledgeMapBranchTopics(node.domainId, node.branch, { offset, limit: 100 });
        items.push(...page.items);
        if (items.length >= page.total || !page.items.length) break;
      }
      if (active) setMembers(items);
    })().catch((requestError) => active && setError(requestError));
    return () => { active = false; };
  }, [node.domainId, node.branch]);
  function move(index, delta) {
    setMembers((current) => {
      const next = [...current];
      [next[index], next[index + delta]] = [next[index + delta], next[index]];
      return next;
    });
  }
  if (error) return <ErrorState error={error} />;
  if (!members) return <Loading label="Loading branch topics" />;
  if (members.length < 2) return <p className="muted-copy">Reordering needs at least two published topics in this branch.</p>;
  return <ProposalForm title={`Reorder ${node.label}`} adminKey={adminKey} onSubmitted={onSubmitted} build={() => ({ action: "REORDER_TOPICS", topic_id: members[0].id, proposed_content: { domain_id: node.domainId, map_branch: node.branch, ordered_topic_ids: members.map((item) => item.id) } })}>
    <ol className="kma-reorder">{members.map((item, index) => <li key={item.id}><span>{item.name}</span><button type="button" aria-label={`Move ${item.name} up`} disabled={index === 0} onClick={() => move(index, -1)}>↑</button><button type="button" aria-label={`Move ${item.name} down`} disabled={index === members.length - 1} onClick={() => move(index, 1)}>↓</button></li>)}</ol>
  </ProposalForm>;
}

function RestoreForm({ topic, adminKey, onSubmitted }) {
  const [history, setHistory] = useState(null);
  const [error, setError] = useState(null);
  const [choice, setChoice] = useState("");
  useEffect(() => {
    fetchKnowledgeContractHistory(topic.id, adminKey).then((result) => setHistory(result.items.filter((item) => item.kind === "version" || item.kind === "section_version"))).catch(setError);
  }, [topic.id, adminKey]);
  if (error) return <ErrorState error={error} />;
  if (!history) return <Loading label="Loading version history" />;
  if (!history.length) return <p className="muted-copy">No earlier versions have been recorded for this topic.</p>;
  const key = (item) => `${item.kind}:${item.section_type || "topic"}:${item.version}`;
  return <ProposalForm title="Restore an earlier version" adminKey={adminKey} onSubmitted={onSubmitted} submitLabel="Propose restore" build={() => {
    const item = history.find((entry) => key(entry) === choice);
    if (!item) return "Choose a version to restore.";
    return { action: "RESTORE_VERSION", topic_id: topic.id, proposed_content: item.kind === "version" ? { target: "topic", version: item.version } : { target: "section", section_type: item.section_type, version: item.version } };
  }}>
    <fieldset className="kma-history"><legend>Versions (newest first)</legend>{history.map((item) => <label key={key(item)} className="kma-history-row"><input type="radio" name={`restore-${topic.id}`} value={key(item)} checked={choice === key(item)} onChange={() => setChoice(key(item))} /><span><strong>{item.kind === "version" ? "Topic" : item.section_type.replaceAll("_", " ")} v{item.version}</strong><small>{item.actor} · {new Date(item.created_at).toLocaleString()} · {item.reason || "No reason recorded"}</small></span></label>)}</fieldset>
    <p className="muted-copy">Restoring creates a proposal; the earlier content is republished as a new version only after review.</p>
  </ProposalForm>;
}

function TopicActions({ node, topic, topics, domains, levels, industries, adminKey, onSubmitted, onEditSections }) {
  const [action, setAction] = useState("PLACE_TOPIC");
  const [domainId, setDomainId] = useState("");
  const [branch, setBranch] = useState("foundations");
  const [otherId, setOtherId] = useState("");
  const [relationshipType, setRelationshipType] = useState("related");
  const [removeKey, setRemoveKey] = useState("");
  const [level, setLevel] = useState({ career_level_id: "", industry_id: "", expectation: "", practical_capability: "" });
  const [reason, setReason] = useState("");
  const [duplicateOf, setDuplicateOf] = useState("");
  const topicId = node.topicId;
  const outgoing = (topic?.related_topics || []).filter((item) => item.direction !== "incoming");
  const forms = {
    PLACE_TOPIC: <PlaceForm topics={topics} domains={domains} adminKey={adminKey} onSubmitted={onSubmitted} fixedTopicId={topicId} />,
    MOVE_TOPIC: <ProposalForm title={`Move out of ${node.domainLabel || "this domain"}`} adminKey={adminKey} onSubmitted={onSubmitted} build={() => (!domainId ? "Choose the destination domain." : { action: "MOVE_TOPIC", topic_id: topicId, proposed_content: { from: { domain_id: node.domainId }, to: { domain_id: Number(domainId), map_branch: branch } } })}>
      <DomainSelect domains={domains} value={domainId} onChange={setDomainId} label="Destination domain" /><BranchSelect value={branch} onChange={setBranch} /><ChildDomainWarning domains={domains} domainId={domainId} />
    </ProposalForm>,
    UNPLACE_TOPIC: <ProposalForm title="Remove from this domain's branch" adminKey={adminKey} onSubmitted={onSubmitted} build={() => ({ action: "UNPLACE_TOPIC", topic_id: topicId, proposed_content: { domain_id: node.domainId } })}>
      <p className="muted-copy">The topic stays linked to the domain (and in Career Readiness); it only leaves the map here.</p>
    </ProposalForm>,
    SET_PARENT_TOPIC: <ProposalForm title="Set parent topic" adminKey={adminKey} onSubmitted={onSubmitted} build={() => ({ action: "SET_PARENT_TOPIC", topic_id: topicId, proposed_content: { parent_topic_id: otherId ? Number(otherId) : null } })}>
      <TopicSelect topics={topics} value={otherId} onChange={setOtherId} exclude={topicId} label="Parent topic" allowNone />
    </ProposalForm>,
    ADD_TOPIC_RELATIONSHIP: <ProposalForm title="Add relationship" adminKey={adminKey} onSubmitted={onSubmitted} build={() => (!otherId ? "Choose the related topic." : { action: "ADD_TOPIC_RELATIONSHIP", topic_id: topicId, proposed_content: { target_topic_id: Number(otherId), relationship_type: relationshipType } })}>
      <label>Relationship<select value={relationshipType} onChange={(event) => setRelationshipType(event.target.value)}>{RELATIONSHIP_TYPES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
      <TopicSelect topics={topics} value={otherId} onChange={setOtherId} exclude={topicId} label="Related topic" />
    </ProposalForm>,
    REMOVE_TOPIC_RELATIONSHIP: outgoing.length ? <ProposalForm title="Remove relationship" adminKey={adminKey} onSubmitted={onSubmitted} build={() => {
      const item = outgoing.find((entry) => `${entry.relationship_type}:${entry.id}` === removeKey);
      return item ? { action: "REMOVE_TOPIC_RELATIONSHIP", topic_id: topicId, proposed_content: { target_topic_id: item.id, relationship_type: item.relationship_type } } : "Choose a relationship to remove.";
    }}>
      <label>Relationship<select value={removeKey} onChange={(event) => setRemoveKey(event.target.value)}><option value="">Choose a relationship</option>{outgoing.map((item) => <option key={`${item.relationship_type}:${item.id}`} value={`${item.relationship_type}:${item.id}`}>{item.label || item.relationship_type}: {item.name}</option>)}</select></label>
    </ProposalForm> : <p className="muted-copy">This topic has no outgoing relationships to remove.</p>,
    UPDATE_CAREER_LEVELS: <ProposalForm title="Career level expectations" adminKey={adminKey} onSubmitted={onSubmitted} build={() => (!level.career_level_id ? "Choose a career level." : { action: "UPDATE_CAREER_LEVELS", topic_id: topicId, proposed_content: { levels: [{ career_level_id: Number(level.career_level_id), industry_id: level.industry_id ? Number(level.industry_id) : null, expectation: level.expectation, practical_capability: level.practical_capability }] } })}>
      <label>Career level<select value={level.career_level_id} onChange={(event) => {
        const chosen = (topic?.level_expectations || []).find((row) => row.career_level.id === Number(event.target.value) && !row.industry);
        setLevel({ ...level, career_level_id: event.target.value, expectation: chosen?.expectation || "", practical_capability: chosen?.practical_capability || "" });
      }}><option value="">Choose a level</option>{["shared", "technical", "management"].map((track) => <optgroup key={track} label={track[0].toUpperCase() + track.slice(1)}>{levels.filter((item) => item.career_track === track).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</optgroup>)}</select></label>
      <label>Industry (optional)<select value={level.industry_id} onChange={(event) => setLevel({ ...level, industry_id: event.target.value })}><option value="">All industries</option>{industries.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>Knowledge<textarea rows="3" maxLength="4000" value={level.expectation} onChange={(event) => setLevel({ ...level, expectation: event.target.value })} /></label>
      <label>Practical skills<textarea rows="3" maxLength="4000" value={level.practical_capability} onChange={(event) => setLevel({ ...level, practical_capability: event.target.value })} /></label>
    </ProposalForm>,
    DEACTIVATE_TOPIC: <ProposalForm title="Deactivate topic" adminKey={adminKey} onSubmitted={onSubmitted} submitLabel="Propose deactivation" build={() => {
      const target = topics.find((item) => item.id === Number(duplicateOf));
      const text = [target ? `Duplicate of ${target.name} (topic ${target.id}).` : "", reason.trim()].filter(Boolean).join(" ");
      return text ? { action: "DEACTIVATE_TOPIC", topic_id: topicId, proposed_content: { reason: text } } : "Give a reason or choose the topic this duplicates.";
    }}>
      <p className="muted-copy">The topic leaves the map and the Knowledge Base once published. Restoring an earlier version brings it back.</p>
      <TopicSelect topics={topics} value={duplicateOf} onChange={setDuplicateOf} exclude={topicId} label="Duplicate of (optional)" />
      <label>Deactivation reason<input value={reason} maxLength="400" onChange={(event) => setReason(event.target.value)} /></label>
    </ProposalForm>,
    RESTORE_VERSION: <RestoreForm topic={{ id: topicId }} adminKey={adminKey} onSubmitted={onSubmitted} />,
  };
  return <section className="kma-actions" aria-label={`Propose changes to ${node.label}`}>
    <div className="kma-actions-header"><p className="eyebrow">PROPOSE A CHANGE</p><button type="button" className="button button-secondary" onClick={() => onEditSections({ id: topicId, name: node.label })}>Edit sections</button></div>
    <div className="kma-action-picker" role="group" aria-label="Change type">{Object.keys(forms).map((id) => <button type="button" key={id} aria-pressed={action === id} className={action === id ? "active" : ""} onClick={() => setAction(id)}>{MAP_ACTION_LABELS[id]}</button>)}</div>
    {forms[action]}
  </section>;
}

// The domain and every domain below it: a domain cannot move under itself or its own sub-domains.
function withDescendants(domains, id) {
  const ids = new Set([id]);
  let grew = true;
  while (grew) {
    grew = false;
    domains.forEach((domain) => { if (ids.has(domain.parent_id) && !ids.has(domain.id)) { ids.add(domain.id); grew = true; } });
  }
  return ids;
}

// Edits, moves, deactivates or deletes the selected domain. Like "Add sub-domain", this saves taxonomy immediately.
function DomainEditForm({ node, domains, adminKey, onChanged }) {
  const domain = domains.find((item) => item.id === node.domainId);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    if (domain) setForm({ name: domain.name, description: domain.description || "", parent_id: domain.parent_id ? String(domain.parent_id) : "", display_order: String(domain.display_order ?? 0) });
  }, [domain?.id, domain?.updated_at]);
  // After a deactivation or deletion the domain leaves the list; keep the confirmation visible.
  if (!domain || !form) return notice ? <p className="success-copy" role="status">{notice}</p> : null;
  const blocked = withDescendants(domains, domain.id);
  const subDomains = blocked.size - 1;
  const change = (field, value) => setForm((current) => ({ ...current, [field]: value }));
  async function run(task, message, previousParentId) {
    setError(null); setNotice(""); setBusy(true);
    try {
      const result = await task();
      setNotice(message(result));
      await onChanged?.(previousParentId);
    } catch (requestError) { setError(requestError); } finally { setBusy(false); }
  }
  function save(event) {
    event.preventDefault();
    if (!form.name.trim()) { setError(new Error("A domain name is required.")); return; }
    const order = Number(form.display_order);
    if (!Number.isInteger(order) || order < 0) { setError(new Error("Display order must be a whole number of 0 or more.")); return; }
    run(() => updateTaxonomyEntry("domain", domain.id, { name: form.name.trim(), description: form.description.trim(), parent_id: form.parent_id ? Number(form.parent_id) : null, display_order: order, expected_updated_at: domain.updated_at }, adminKey),
      (updated) => `${updated.name} was saved.`, domain.parent_id);
  }
  function deactivate() {
    const extra = subDomains ? ` Its ${subDomains} sub-domain${subDomains === 1 ? "" : "s"} will be hidden too.` : "";
    if (!window.confirm(`Deactivate ${domain.name}? It and its topic branches leave the map.${extra} You can reactivate it in Taxonomy Management.`)) return;
    run(() => setTaxonomyActive("domain", domain.id, false, adminKey), () => `${domain.name} was deactivated. Reactivate it in Taxonomy Management.`, domain.parent_id);
  }
  function remove() {
    if (!window.confirm(`Permanently delete ${domain.name}? This only works when nothing uses it.`)) return;
    run(() => deleteTaxonomyEntry("domain", domain.id, adminKey), () => `${domain.name} was deleted.`, domain.parent_id);
  }
  return <form className="kma-form" onSubmit={save} aria-label="Edit domain">
    <h3>Edit domain</h3>
    <p className="muted-copy">Rename, describe, reorder or move this domain under another parent. Changes are saved immediately, like in Taxonomy Management.</p>
    <label>Domain name<input value={form.name} maxLength="180" onChange={(event) => change("name", event.target.value)} /></label>
    <label>Description<textarea rows="2" maxLength="4000" value={form.description} onChange={(event) => change("description", event.target.value)} /></label>
    <DomainSelect domains={domains.filter((item) => !blocked.has(item.id))} value={form.parent_id} onChange={(value) => change("parent_id", value)} label="Parent domain" emptyLabel="Top level (no parent)" />
    <label>Display order<input type="number" min="0" max="100000" value={form.display_order} onChange={(event) => change("display_order", event.target.value)} /></label>
    {error && <p className="kma-error" role="alert">{error.message}</p>}
    {notice && <p className="success-copy" role="status">{notice}</p>}
    <div className="review-card-actions">
      <button type="submit" className="button" disabled={busy}>{busy ? "Saving…" : "Save domain"}</button>
      <button type="button" className="button button-secondary" disabled={busy} onClick={deactivate}>Deactivate</button>
      <button type="button" className="button button-secondary" disabled={busy} onClick={remove}>Delete if unused</button>
    </div>
  </form>;
}

export default function KnowledgeMapAdminPage({ onNavigate }) {
  const [enteredKey, setEnteredKey] = useState(() => getAdminSessionKey());
  const [adminKey, setAdminKey] = useState(() => getAdminSessionKey());
  const [data, setData] = useState({ loading: true, error: null, topics: [], domains: [], levels: [], industries: [], proposals: [] });
  const [editing, setEditing] = useState(null);
  const [newTopic, setNewTopic] = useState({ name: "", description: "", domain_id: "", map_branch: "foundations" });

  const load = useCallback(async () => {
    if (!adminKey) return;
    setData((current) => ({ ...current, loading: true, error: null }));
    try {
      const [topics, domains, levels, industries, queue] = await Promise.all([fetchKnowledgeAdminTopics(adminKey), fetchDomains(), fetchLevels(), fetchIndustries(), fetchKnowledgeReviewQueue({ group: "map", limit: 500 }, adminKey)]);
      setData({ loading: false, error: null, topics: topics.sort((a, b) => a.name.localeCompare(b.name)), domains: flattenDomains(domains).filter((domain) => domain.is_active !== false), levels, industries, proposals: queue.items });
    } catch (error) { setData((current) => ({ ...current, loading: false, error })); }
  }, [adminKey]);
  useEffect(() => { load(); }, [load]);

  const pending = useMemo(() => pendingIndex(data.proposals), [data.proposals]);
  const openProposals = data.proposals.filter((item) => OPEN_STATUSES.has(item.status));
  const topicById = useMemo(() => new Map(data.topics.map((topic) => [topic.id, topic])), [data.topics]);
  const activeTopics = useMemo(() => data.topics.filter((topic) => topic.is_active !== false), [data.topics]);
  const duplicates = useMemo(() => possibleDuplicates(data.topics, newTopic.name), [data.topics, newTopic.name]);

  const badgeFor = useCallback((node) => {
    if (node.type === "topic" && pending.topics.has(node.topicId)) return "Pending";
    if (node.type === "branch" && pending.branches.has(node.id)) return "Pending";
    return null;
  }, [pending]);

  const renderDetails = useCallback((node, { state, reloadChildren }) => {
    const parentLabel = state.nodes[state.parents[node.id]]?.label;
    if (node.type === "topic") return <TopicActions key={node.id} node={{ ...node, domainLabel: state.nodes[state.parents[state.parents[node.id]]]?.label }} topic={topicById.get(node.topicId)} topics={activeTopics} domains={data.domains} levels={data.levels} industries={data.industries} adminKey={adminKey} onSubmitted={load} onEditSections={setEditing} />;
    if (node.type === "branch") return <section className="kma-actions" key={node.id} aria-label={`Propose changes to ${parentLabel} ${node.label}`}><p className="eyebrow">PROPOSE A CHANGE</p><ReorderForm node={node} adminKey={adminKey} onSubmitted={load} /><PlaceForm topics={activeTopics} domains={data.domains} adminKey={adminKey} onSubmitted={load} fixedDomainId={node.domainId} fixedBranch={node.branch} /></section>;
    if (node.type === "domain" || node.type === "child-domain") return <section className="kma-actions" key={node.id} aria-label={`Propose changes to ${node.label}`}><p className="eyebrow">PROPOSE A CHANGE</p><PlaceForm topics={activeTopics} domains={data.domains} adminKey={adminKey} onSubmitted={load} fixedDomainId={node.domainId} /><SubDomainForm parent={node} domains={data.domains} adminKey={adminKey} onCreated={() => Promise.all([load(), reloadChildren(node.id)])} /><DomainEditForm node={node} domains={data.domains} adminKey={adminKey} onChanged={async (previousParentId) => {
      // Refresh where the domain was and where it is now, so renames, moves and removals all show on the map.
      const [domains] = await Promise.all([fetchDomains().then(flattenDomains), load()]);
      const now = domains.find((item) => item.id === node.domainId);
      const ids = new Set([previousParentId ? domainNodeId(previousParentId) : ROOT_ID, now ? (now.parent_id ? domainNodeId(now.parent_id) : ROOT_ID) : null].filter(Boolean));
      await Promise.all([...ids].map((id) => reloadChildren(id)));
    }} /></section>;
    return null;
  }, [topicById, activeTopics, data.domains, data.levels, data.industries, adminKey, load]);

  const admin = useMemo(() => ({ badgeFor, renderDetails }), [badgeFor, renderDetails]);

  function unlock() { if (enteredKey.trim()) { setAdminSessionKey(enteredKey.trim()); setAdminKey(enteredKey.trim()); } }
  function lock() { clearAdminSessionKey(); setEnteredKey(""); setAdminKey(""); }

  const header = <PageHeader eyebrow="ADMINISTRATION / KNOWLEDGE MAP" title="Knowledge Map Management" description="Add sub-domains at any depth, then propose placements, ordering, hierarchy and topic changes in each domain's Foundations, Security and Common Vulnerabilities. Topic changes are proposals: they reach the public map only after review and explicit publication in Knowledge Review.">
    {adminKey && <div className="review-card-actions"><button className="button button-secondary" onClick={() => onNavigate?.("knowledge-review")}>Open Knowledge Review</button><button className="button button-secondary" onClick={() => onNavigate?.("taxonomy-management")}>Manage domains in Taxonomy Management</button><button className="button button-secondary" onClick={lock}>Lock workspace</button></div>}
  </PageHeader>;

  if (!adminKey) return <>{header}<section className="panel research-auth"><p className="eyebrow">ADMINISTRATOR ACCESS</p><h2>Unlock Knowledge Map Management</h2><input aria-label="Administrator API key" type="password" value={enteredKey} onChange={(event) => setEnteredKey(event.target.value)} placeholder="X-Admin-API-Key" /><button className="button" disabled={!enteredKey.trim()} onClick={unlock}>Open Knowledge Map Management</button></section></>;

  return <div className="knowledge-map-admin">
    {header}
    {data.error && <ErrorState error={data.error} onRetry={load} />}
    {data.loading && !data.topics.length ? <Loading label="Loading knowledge map management" /> : <>
      <div className="kma-top">
        <section className="panel kma-new-topic">
          <ProposalForm title="New topic" adminKey={adminKey} onSubmitted={() => { setNewTopic({ name: "", description: "", domain_id: "", map_branch: "foundations" }); load(); }} build={() => {
            if (!newTopic.name.trim()) return "A topic name is required.";
            if (duplicates.some((item) => item.exact)) return "A topic with this name already exists. Place or update the existing topic instead.";
            return { action: "CREATE_TOPIC", topic_name: newTopic.name.trim(), proposed_content: { topic: { name: newTopic.name.trim(), description: newTopic.description.trim() }, ...(newTopic.domain_id ? { placements: [{ domain_id: Number(newTopic.domain_id), map_branch: newTopic.map_branch }] } : {}) } };
          }}>
            <label>Name<input value={newTopic.name} maxLength="240" onChange={(event) => setNewTopic({ ...newTopic, name: event.target.value })} /></label>
            {duplicates.length > 0 && <div className="kma-duplicates" role="note"><span className="field-label">Possible duplicates</span><ul>{duplicates.map(({ topic, exact }) => <li key={topic.id}>{topic.name} {exact ? <Badge tone="violet">Same name, key or alias</Badge> : <Badge>Similar</Badge>}</li>)}</ul></div>}
            <label>Description<textarea rows="2" maxLength="2000" value={newTopic.description} onChange={(event) => setNewTopic({ ...newTopic, description: event.target.value })} /></label>
            <DomainSelect domains={data.domains} value={newTopic.domain_id} onChange={(value) => setNewTopic({ ...newTopic, domain_id: value })} label="Place in domain (optional)" />
            {newTopic.domain_id && <BranchSelect value={newTopic.map_branch} onChange={(value) => setNewTopic({ ...newTopic, map_branch: value })} />}
            <ChildDomainWarning domains={data.domains} domainId={newTopic.domain_id} />
          </ProposalForm>
        </section>
        <section className="panel kma-pending">
          <div className="panel-title-row"><div><p className="eyebrow">PENDING MAP CHANGES</p><h2>{openProposals.length} open {openProposals.length === 1 ? "proposal" : "proposals"}</h2></div><button type="button" className="button button-secondary" onClick={load}>Refresh</button></div>
          {openProposals.length ? <ul className="kma-pending-list">{openProposals.slice(0, 12).map((item) => <li key={item.id}><span className="km-pending-badge">Pending</span><strong>{MAP_ACTION_LABELS[item.action] || item.action}</strong><span>{item.topic_key || item.proposed_content?.topic?.name || "New topic"}</span><Badge>{item.status}</Badge></li>)}</ul> : <EmptyState title="No pending map changes" message="Proposals you submit here appear in this list and in Knowledge Review until they are published or rejected." />}
        </section>
      </div>
      <KnowledgeMapSuggestions adminKey={adminKey} onSubmitted={load} />
      <p className="muted-copy kma-hint">Select a domain, branch or topic on the map to propose a change for it. “Pending” marks items with open proposals; the public map never shows these badges.</p>
      <KnowledgeMapPage onNavigate={onNavigate} admin={admin} />
    </>}
    {editing && <KnowledgeSectionEditor topic={editing} adminKey={adminKey} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />}
  </div>;
}
