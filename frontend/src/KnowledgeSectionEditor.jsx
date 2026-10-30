import { useEffect, useMemo, useState } from "react";

import { createKnowledgeProposal, fetchKnowledgeAdminTopic, fetchLevels } from "./api";
import { Badge, ErrorState, Loading } from "./components";

const sectionLabels = { overview: "Overview", how_it_works: "How It Works", attack_surfaces: "Attack Surfaces", mitigations: "Mitigations", real_world_examples: "Real-World Examples", references: "References", career_level_guidance: "Career-Level Guidance", code_examples: "Code Examples", architecture: "Architecture Diagrams" };
const defaults = {
  overview: { short_description: "", technical_explanation: "", key_concepts: [], related_technologies: [] },
  how_it_works: { workflow: "", architecture_explanation: "", diagram: { nodes: [], edges: [] }, steps: [] },
  attack_surfaces: { items: [] },
  mitigations: { items: [] },
  real_world_examples: { items: [] },
  references: { items: [] },
  code_examples: { items: [] },
  architecture: { diagrams: [] },
};

// Career-level guidance keys come from the active career levels, never a hardcoded list.
function sectionDefaults(section, levels) {
  if (section === "career_level_guidance") return { levels: Object.fromEntries(levels.map((level) => [level.slug, ""])) };
  return defaults[section];
}

export default function KnowledgeSectionEditor({ topic, adminKey, onClose, onSaved }) {
  const [section, setSection] = useState("overview");
  const [detail, setDetail] = useState(topic);
  const [content, setContent] = useState(defaults.overview);
  const [levels, setLevels] = useState([]);
  const [reference, setReference] = useState({ source_type: "technical_article", title: "", url: "", locator: "", excerpt: "", verification_status: "unverified" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  useEffect(() => { fetchKnowledgeAdminTopic(topic.id, adminKey).then(setDetail).catch(setError); }, [topic.id, adminKey]);
  useEffect(() => { fetchLevels().then(setLevels).catch(() => setLevels([])); }, []);
  const current = useMemo(() => detail.sections?.find((item) => item.section_type === section), [detail.sections, section]);
  useEffect(() => { setContent(current?.content || sectionDefaults(section, levels)); }, [current, section, levels]);
  const existing = current?.content ? `Existing published section: version ${current.published_version}` : "No published section yet";
  async function save(submitForReview) {
    setBusy(true); setError(null); setNotice(null);
    try {
      await createKnowledgeProposal({ schema_version: "1.0", source_type: "manual", topic_id: topic.id, action: current ? "UPDATE_SECTION" : "ADD_SECTION", section, proposed_content: content, change_reason: `Administrator edited ${sectionLabels[section]}.`, submit_for_review: submitForReview, references: reference.title.trim() ? [reference] : [] }, adminKey, `manual-${topic.id}-${section}-${Date.now()}`);
      setNotice(submitForReview ? "Section submitted for review." : "Section saved as a draft.");
      onSaved?.();
    } catch (requestError) { setError(requestError); } finally { setBusy(false); }
  }
  function updateJson(value) { try { setContent(JSON.parse(value)); setError(null); } catch { setError(new Error("Section content must be valid JSON.")); } }
  return <div className="review-modal-backdrop" role="presentation"><section className="panel knowledge-section-editor" role="dialog" aria-modal="true" aria-labelledby="knowledge-section-editor-title"><div className="panel-title-row"><div><p className="eyebrow">KNOWLEDGE BASE MANAGEMENT</p><h2 id="knowledge-section-editor-title">Edit {topic.name}</h2><p className="muted-copy">{existing}. Published content remains unchanged until explicit approval and publication.</p></div><button type="button" className="text-link" onClick={onClose}>Close</button></div>{error && <ErrorState error={error} />}{notice && <p className="success-copy" role="status">{notice}</p>}<label>Section<select value={section} onChange={(event) => setSection(event.target.value)}>{Object.entries(sectionLabels).map(([id, label]) => <option value={id} key={id}>{label}</option>)}</select></label><label>Structured section content<small className="hint">Use the schema shown in the preview. Arrays support multiple independently reviewable entries.</small><textarea className="knowledge-json-editor" rows="16" value={JSON.stringify(content, null, 2)} onChange={(event) => updateJson(event.target.value)} /></label><section className="knowledge-section-preview"><div className="panel-title-row"><div><span className="field-label">Preview</span><strong>{sectionLabels[section]}</strong></div><Badge tone="violet">Draft preview</Badge></div><pre>{JSON.stringify(content, null, 2)}</pre></section><section className="knowledge-reference-form"><span className="field-label">Supporting source (optional)</span><div className="review-edit-grid"><label>Source type<input value={reference.source_type} onChange={(event) => setReference({ ...reference, source_type: event.target.value })} /></label><label>Title<input value={reference.title} onChange={(event) => setReference({ ...reference, title: event.target.value })} /></label><label>URL<input value={reference.url} onChange={(event) => setReference({ ...reference, url: event.target.value })} /></label><label>Locator<input value={reference.locator} onChange={(event) => setReference({ ...reference, locator: event.target.value })} placeholder="Page or section" /></label><label>Excerpt<textarea rows="2" maxLength="6000" value={reference.excerpt} onChange={(event) => setReference({ ...reference, excerpt: event.target.value })} /></label><label>Verification<select value={reference.verification_status} onChange={(event) => setReference({ ...reference, verification_status: event.target.value })}><option value="unverified">Unverified</option><option value="verified">Verified</option><option value="authoritative">Authoritative</option></select></label></div></section><div className="review-card-actions"><button type="button" className="button button-secondary" disabled={busy} onClick={() => save(false)}>Save draft</button><button type="button" className="button" disabled={busy} onClick={() => save(true)}>{busy ? "Saving…" : "Submit for review"}</button></div>{busy && <Loading label="Saving knowledge proposal" />}</section></div>;
}
