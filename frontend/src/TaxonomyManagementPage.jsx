import { useEffect, useMemo, useState } from "react";

import {
  clearAdminSessionKey,
  createTaxonomyEntry,
  deleteTaxonomyEntry,
  fetchTaxonomyHistory,
  fetchTaxonomyImpact,
  fetchTaxonomyManagement,
  getAdminSessionKey,
  mergeTaxonomyEntry,
  setAdminSessionKey,
  setTaxonomyActive,
  updateTaxonomyEntry,
} from "./api";
import { Badge, EmptyState, ErrorState, Loading, PageHeader } from "./components";

const TABS = [
  ["domain", "Security Domains"],
  ["industry", "Industries"],
  ["career_level", "Career Levels"],
  ["category", "Competency Categories"],
  ["history", "Change History"],
];
const TYPE_LABELS = Object.fromEntries(TABS);
const TYPE_SINGULAR = { domain: "Security Domain", industry: "Industry", career_level: "Career Level", category: "Competency Category" };

const blankForm = (type) => ({
  name: "",
  slug: "",
  description: "",
  parent_id: "",
  career_track: "shared",
  display_order: 0,
  is_active: true,
  aliases: "",
});

function toForm(entry) {
  return {
    name: entry.name,
    slug: entry.slug,
    description: entry.description || "",
    parent_id: entry.parent_id || "",
    career_track: entry.career_track || "shared",
    display_order: entry.display_order || 0,
    is_active: entry.is_active,
    aliases: (entry.aliases || []).map((alias) => alias.alias).join("\n"),
  };
}

function aliasPayload(value) {
  return value.split("\n").map((alias) => alias.trim()).filter(Boolean).map((alias) => ({ alias }));
}

function EntryRow({ entry, type, onEdit, onImpact, onToggle, onDelete, onMerge, depth = 0 }) {
  return <>
    <article className={`taxonomy-entry-row ${!entry.is_active ? "inactive" : ""}`} style={{ "--taxonomy-depth": depth }}>
      <div className="taxonomy-entry-main">
        <span className="taxonomy-tree-marker">{type === "domain" && entry.children?.length ? "⌄" : depth ? "↳" : "·"}</span>
        <div>
          <div className="taxonomy-entry-title"><strong>{entry.name}</strong><Badge tone={entry.is_active ? "mint" : "neutral"}>{entry.is_active ? "Active" : "Inactive"}</Badge></div>
          <small>{entry.slug}{entry.parent_name ? ` · under ${entry.parent_name}` : ""}</small>
          {entry.description && <p>{entry.description}</p>}
          {entry.aliases?.length > 0 && <div className="taxonomy-alias-list">{entry.aliases.map((alias) => <span key={alias.alias}>{alias.alias}</span>)}</div>}
        </div>
      </div>
      <div className="taxonomy-entry-meta">
        <span>Order <strong>{entry.display_order}</strong></span>
        {entry.career_track && <span>{entry.career_track}</span>}
        <span>{Object.values(entry.dependencies || {}).reduce((sum, value) => sum + value, 0)} dependencies</span>
      </div>
      <div className="taxonomy-entry-actions">
        <button type="button" className="button button-secondary" onClick={() => onEdit(entry)}>Edit</button>
        <button type="button" className="button button-secondary" onClick={() => onImpact(entry)}>Impact</button>
        <button type="button" className="button button-secondary" onClick={() => onMerge(entry)}>Merge</button>
        <button type="button" className="button button-secondary" onClick={() => onToggle(entry)}>{entry.is_active ? "Deactivate" : "Reactivate"}</button>
        {!Object.values(entry.dependencies || {}).some(Boolean) && <button type="button" className="button button-danger" onClick={() => onDelete(entry)}>Delete</button>}
      </div>
    </article>
    {type === "domain" && entry.children?.map((child) => <EntryRow key={child.id} entry={child} type={type} onEdit={onEdit} onImpact={onImpact} onToggle={onToggle} onDelete={onDelete} onMerge={onMerge} depth={depth + 1} />)}
  </>;
}

function ImpactDialog({ impact, onClose }) {
  if (!impact) return null;
  return <div className="review-modal-backdrop" role="presentation"><section className="panel review-modal taxonomy-impact-dialog" role="dialog" aria-modal="true" aria-labelledby="taxonomy-impact-title">
    <p className="eyebrow">DEPENDENCY IMPACT</p><h2 id="taxonomy-impact-title">{impact.entry.name}</h2>
    <p className="muted-copy">Existing evidence and published expectations remain preserved when this entry is deactivated or merged.</p>
    <div className="taxonomy-impact-grid">{Object.entries(impact.dependencies || {}).map(([key, value]) => <div key={key}><strong>{value}</strong><span>{key.replaceAll("_", " ")}</span></div>)}</div>
    {impact.blockers?.length > 0 && <div className="classification-warning"><strong>Permanent deletion is blocked</strong>{impact.blockers.map((blocker) => <span key={blocker}>{blocker}</span>)}</div>}
    <button type="button" className="button button-secondary" onClick={onClose}>Close</button>
  </section></div>;
}

function MergeDialog({ source, entries, type, saving, onClose, onSubmit }) {
  const [targetId, setTargetId] = useState("");
  const target = entries.find((entry) => String(entry.id) === String(targetId));
  return <div className="review-modal-backdrop" role="presentation"><section className="panel review-modal taxonomy-impact-dialog" role="dialog" aria-modal="true" aria-labelledby="taxonomy-merge-title">
    <p className="eyebrow">ADMINISTRATOR MERGE</p><h2 id="taxonomy-merge-title">Merge {source.name}</h2>
    <div className="taxonomy-merge-preview"><div><span>Source</span><strong>{source.name}</strong><small>{source.dependencies?.research_findings || 0} research findings · {source.dependencies?.published_expectations || 0} published expectations</small></div><span className="merge-arrow">→</span><label>Target<select aria-label="Merge target" value={targetId} onChange={(event) => setTargetId(event.target.value)}><option value="">Choose an active target</option>{entries.filter((entry) => entry.id !== source.id && entry.is_active).map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}</select></label></div>
    {target && <div className="classification-warning"><strong>Review before confirmation</strong><span>All supported research, evidence, expectations, and classifications will be reassigned to {target.name}. The source will be retained as inactive and recorded in history.</span></div>}
    <div className="review-card-actions"><button type="button" className="button button-secondary" disabled={saving} onClick={onClose}>Cancel</button><button type="button" className="button button-danger" disabled={saving || !targetId} onClick={() => onSubmit(Number(targetId))}>{saving ? "Merging…" : "Confirm merge"}</button></div>
  </section></div>;
}

function TaxonomyDrawer({ type, entry, parents, saving, error, onClose, onSubmit }) {
  const [form, setForm] = useState(() => entry ? toForm(entry) : blankForm(type));
  const [validation, setValidation] = useState("");
  function change(field, value) { setForm((current) => ({ ...current, [field]: value })); setValidation(""); }
  function submit(event) {
    event.preventDefault();
    if (!form.name.trim()) { setValidation("Name is required."); return; }
    if (Number(form.display_order) < 0 || !Number.isInteger(Number(form.display_order))) { setValidation("Display order must be a non-negative whole number."); return; }
    onSubmit({ ...form, name: form.name.trim(), slug: form.slug.trim() || undefined, description: form.description.trim(), parent_id: form.parent_id ? Number(form.parent_id) : null, display_order: Number(form.display_order), aliases: aliasPayload(form.aliases), ...(entry ? { expected_updated_at: entry.updated_at } : {}) });
  }
  return <div className="review-modal-backdrop" role="presentation"><section className="panel taxonomy-drawer" role="dialog" aria-modal="true" aria-labelledby="taxonomy-drawer-title">
    <div className="panel-title-row"><div><p className="eyebrow">{entry ? "EDIT ENTRY" : "NEW ENTRY"}</p><h2 id="taxonomy-drawer-title">{entry ? `Edit ${entry.name}` : `Add ${TYPE_SINGULAR[type]}`}</h2></div><button type="button" className="button button-secondary" onClick={onClose}>Close</button></div>
    <form className="taxonomy-form" onSubmit={submit}>
      <label>Name<input autoFocus required value={form.name} onChange={(event) => change("name", event.target.value)} placeholder="Canonical taxonomy name" /></label>
      <label>Slug <span className="hint">generated when empty</span><input value={form.slug} onChange={(event) => change("slug", event.target.value)} placeholder="safe-url-slug" /></label>
      <label className="taxonomy-form-wide">Description<textarea rows="4" value={form.description} onChange={(event) => change("description", event.target.value)} /></label>
      {(type === "domain" || type === "industry") && <label>Parent {type === "domain" ? "domain" : "industry"}<select value={form.parent_id} onChange={(event) => change("parent_id", event.target.value)}><option value="">Top level</option>{parents.filter((parent) => parent.id !== entry?.id).map((parent) => <option key={parent.id} value={parent.id}>{parent.name}</option>)}</select></label>}
      {type === "career_level" && <label>Career track<select value={form.career_track} onChange={(event) => change("career_track", event.target.value)}><option value="technical">Technical</option><option value="management">Management</option><option value="shared">Cross-Track</option></select></label>}
      <label>Display order<input type="number" min="0" step="1" value={form.display_order} onChange={(event) => change("display_order", event.target.value)} /></label>
      <label className="taxonomy-form-wide">Aliases <span className="hint">one per line; use context-aware aliases carefully</span><textarea rows="4" value={form.aliases} onChange={(event) => change("aliases", event.target.value)} placeholder="Alternative label" /></label>
      <label className="taxonomy-checkbox"><input type="checkbox" checked={form.is_active} onChange={(event) => change("is_active", event.target.checked)} /> Active and available for new classification</label>
      {(validation || error) && <p className="error-copy taxonomy-form-wide" role="alert">{validation || error.message}</p>}
      <div className="review-card-actions taxonomy-form-wide"><button type="button" className="button button-secondary" disabled={saving} onClick={onClose}>Cancel</button><button className="button" disabled={saving}>{saving ? "Saving…" : entry ? "Save changes" : "Create entry"}</button></div>
    </form>
  </section></div>;
}

export default function TaxonomyManagementPage() {
  const [enteredKey, setEnteredKey] = useState(() => getAdminSessionKey());
  const [adminKey, setAdminKey] = useState(() => getAdminSessionKey());
  const [tab, setTab] = useState("domain");
  const [items, setItems] = useState([]);
  const [history, setHistory] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState("");
  const [drawer, setDrawer] = useState(null);
  const [impact, setImpact] = useState(null);
  const [mergeSource, setMergeSource] = useState(null);

  async function load() {
    if (!adminKey) return;
    setLoading(true); setError(null);
    try {
      const [management, historyResponse] = await Promise.all([fetchTaxonomyManagement({ include_inactive: true }, adminKey), fetchTaxonomyHistory({}, adminKey)]);
      setItems(management.items); setHistory(historyResponse.items);
    } catch (requestError) { setError(requestError); } finally { setLoading(false); }
  }
  useEffect(() => { if (adminKey) load(); }, [adminKey]);

  const entries = useMemo(() => items.filter((entry) => entry.taxonomy_type === tab), [items, tab]);
  const flatEntries = useMemo(() => {
    const result = [];
    function visit(entry) { result.push(entry); (entry.children || []).forEach(visit); }
    entries.filter((entry) => tab !== "domain" || entry.parent_id === null).forEach(visit);
    return tab === "domain" ? result : entries;
  }, [entries, tab]);
  const visibleEntries = useMemo(() => flatEntries.filter((entry) => !search.trim() || `${entry.name} ${entry.slug} ${entry.description} ${(entry.aliases || []).map((alias) => alias.alias).join(" ")}`.toLowerCase().includes(search.toLowerCase())), [flatEntries, search]);

  function openDrawer(entry = null) { setError(null); setNotice(""); setDrawer({ type: tab, entry }); }
  async function submitEntry(payload) {
    setSaving(true); setError(null);
    try { if (drawer.entry) await updateTaxonomyEntry(drawer.type, drawer.entry.id, payload, adminKey); else await createTaxonomyEntry(drawer.type, payload, adminKey); setDrawer(null); setNotice(`${TYPE_SINGULAR[drawer.type]} ${drawer.entry ? "updated" : "created"}.`); await load(); } catch (requestError) { setError(requestError); } finally { setSaving(false); }
  }
  async function toggle(entry) {
    setSaving(true); setError(null);
    try { await setTaxonomyActive(entry.taxonomy_type, entry.id, !entry.is_active, adminKey); setNotice(`${entry.name} is now ${entry.is_active ? "inactive" : "active"}.`); await load(); } catch (requestError) { setError(requestError); } finally { setSaving(false); }
  }
  async function remove(entry) {
    if (!window.confirm(`Permanently delete unused ${entry.name}?`)) return;
    setSaving(true); setError(null);
    try { await deleteTaxonomyEntry(entry.taxonomy_type, entry.id, adminKey); setNotice(`${entry.name} was deleted.`); await load(); } catch (requestError) { setError(requestError); } finally { setSaving(false); }
  }
  async function merge(targetId) {
    setSaving(true); setError(null);
    try { await mergeTaxonomyEntry(mergeSource.taxonomy_type, mergeSource.id, { target_id: targetId, confirm: true, expected_updated_at: mergeSource.updated_at }, adminKey); setMergeSource(null); setNotice(`${mergeSource.name} was merged and retained as inactive history.`); await load(); } catch (requestError) { setError(requestError); } finally { setSaving(false); }
  }
  async function showImpact(entry) { setError(null); try { setImpact(await fetchTaxonomyImpact(entry.taxonomy_type, entry.id, adminKey)); } catch (requestError) { setError(requestError); } }

  if (!adminKey) return <><PageHeader eyebrow="RESEARCH ADMIN / TAXONOMY" title="Taxonomy Management" description="Maintain the shared security taxonomy used by research ingestion, review, readiness, analytics, and exploration." /><section className="panel research-auth"><p className="eyebrow">ADMINISTRATOR ACCESS</p><h2>Unlock taxonomy management</h2><p className="muted-copy">Taxonomy mutations are restricted to administrators and stay in this browser session only.</p><input aria-label="Administrator API key" type="password" placeholder="X-Admin-API-Key" value={enteredKey} onChange={(event) => setEnteredKey(event.target.value)} /><button className="button" disabled={!enteredKey} onClick={() => { setAdminSessionKey(enteredKey); setAdminKey(enteredKey); }}>Open taxonomy management</button></section></>;

  return <>
    <PageHeader eyebrow="RESEARCH ADMIN / TAXONOMY" title="Taxonomy Management" description="Manage the shared, auditable taxonomy without editing source code or database records manually."><button className="button button-secondary" onClick={() => { clearAdminSessionKey(); setAdminKey(""); setEnteredKey(""); }}>Lock workspace</button></PageHeader>
    {error && <ErrorState error={error} onRetry={load} />}{notice && <p className="success-copy" role="status">{notice}</p>}
    <section className="panel taxonomy-management-panel">
      <div className="taxonomy-tabs" role="tablist">{TABS.map(([id, label]) => <button type="button" role="tab" aria-selected={tab === id} className={tab === id ? "active" : ""} key={id} onClick={() => { setTab(id); setSearch(""); }}>{label}</button>)}</div>
      {tab === "history" ? <div className="taxonomy-history"><div className="panel-title-row"><div><p className="eyebrow">AUDIT TRAIL</p><h2>Taxonomy changes</h2></div><button className="button button-secondary" onClick={load}>Refresh</button></div>{history.length ? history.map((event) => <article className="taxonomy-history-row" key={event.id}><Badge tone={event.action === "merged" ? "violet" : event.action === "deactivated" ? "amber" : "mint"}>{event.action.replaceAll("_", " ")}</Badge><div><strong>{event.taxonomy_type.replaceAll("_", " ")} #{event.entry_id}</strong><small>{event.actor} · {new Date(event.created_at).toLocaleString()}</small></div>{event.merge_target_id && <span>target #{event.merge_target_id}</span>}</article>) : <EmptyState title="No taxonomy changes yet" message="Create, edit, merge, or deactivate an entry to record the first change." />}</div> : <>
        <div className="panel-title-row taxonomy-toolbar"><div><p className="eyebrow">{TYPE_LABELS[tab]}</p><h2>{entries.length} entries</h2></div><div className="taxonomy-toolbar-actions"><input aria-label="Search taxonomy" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search names or aliases" /><button className="button" onClick={() => openDrawer()}>Add {TYPE_LABELS[tab].replace(/s$/, "")}</button></div></div>
        {loading ? <Loading label="Loading taxonomy" /> : visibleEntries.length ? <div className="taxonomy-entry-list">{visibleEntries.filter((entry) => tab !== "domain" || entry.parent_id === null || search.trim()).map((entry) => <EntryRow key={`${entry.taxonomy_type}-${entry.id}`} entry={entry} type={tab} onEdit={openDrawer} onImpact={showImpact} onToggle={toggle} onDelete={remove} onMerge={setMergeSource} />)}</div> : <EmptyState title="No matching taxonomy entries" message={search ? "Try a different search term." : "Add the first shared taxonomy entry."} />}
      </>}
    </section>
    {drawer && <TaxonomyDrawer type={drawer.type} entry={drawer.entry} parents={flatEntries} saving={saving} error={error} onClose={() => setDrawer(null)} onSubmit={submitEntry} />}
    {impact && <ImpactDialog impact={impact} onClose={() => setImpact(null)} />}
    {mergeSource && <MergeDialog source={mergeSource} entries={flatEntries} type={mergeSource.taxonomy_type} saving={saving} onClose={() => setMergeSource(null)} onSubmit={merge} />}
  </>;
}
