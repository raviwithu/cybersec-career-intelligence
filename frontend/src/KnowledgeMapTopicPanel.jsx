import { useEffect, useId, useMemo, useRef, useState } from "react";

import { fetchKnowledgeContractTopic, fetchLevels } from "./api";
import { Badge, ErrorState, Loading } from "./components";
import { LegacyCareerGuidance, SectionContent, sectionsByType, useRelatedGroups } from "./KnowledgeSections";

// Topic detail panel for the Security Knowledge Map. Tabs appear only when the topic has published content for them.

const TABS = [
  ["overview", "Overview"],
  ["how_it_works", "How It Works"],
  ["code_examples", "Example Code"],
  ["attack_surfaces", "Attack Surface"],
  ["mitigations", "Mitigations"],
  ["real_world_examples", "Real-World CVEs"],
  ["architecture", "Architecture"],
  ["career_levels", "Career Levels"],
  ["related", "Related Topics"],
  ["references", "References"],
];
const TRACKS = [["shared", "Shared"], ["technical", "Technical"], ["management", "Management"]];

function availableTabs(topic, sections) {
  return TABS.filter(([id]) => {
    if (id === "career_levels") return topic.level_expectations?.length > 0 || Boolean(sections.career_level_guidance);
    if (id === "related") return topic.related_topics?.length > 0;
    if (id === "architecture") return sections.architecture?.content?.diagrams?.length > 0 || sections.architecture?.content?.hidden_diagram_count > 0;
    return Boolean(sections[id]);
  });
}

function ExpectationText({ rows, field, empty }) {
  const filled = rows.filter((row) => row[field]);
  if (!filled.length) return <p className="muted-copy">{empty}</p>;
  return filled.map((row, index) => <p key={`${row.industry?.id || "general"}-${index}`}>{row.industry && <Badge tone="blue">{row.industry.name}</Badge>} {row[field]}</p>);
}

function CareerLevels({ expectations, legacy }) {
  const [levels, setLevels] = useState({ loading: true, error: null, items: [] });
  const [levelId, setLevelId] = useState(null);
  const load = () => {
    setLevels({ loading: true, error: null, items: [] });
    fetchLevels().then((items) => setLevels({ loading: false, error: null, items })).catch((error) => setLevels({ loading: false, error, items: [] }));
  };
  useEffect(load, []);
  if (!expectations.length) return <div className="kx-legacy"><p className="muted-copy">Legacy career guidance, shown read-only until per-level expectations are published.</p>{legacy ? <LegacyCareerGuidance content={legacy.content || {}} /> : null}</div>;
  if (levels.loading) return <Loading label="Loading career levels" />;
  if (levels.error) return <ErrorState error={levels.error} onRetry={load} />;
  const chosenId = levelId ?? (levels.items.find((level) => expectations.some((row) => row.career_level.id === level.id)) || levels.items[0])?.id;
  const chosen = levels.items.find((level) => level.id === chosenId);
  const rows = expectations.filter((row) => row.career_level.id === chosenId);
  return <div className="kx-levels">
    <label>Career level<select value={chosenId ?? ""} onChange={(event) => setLevelId(Number(event.target.value))}>
      {TRACKS.map(([track, label]) => {
        const items = levels.items.filter((level) => level.career_track === track);
        return items.length ? <optgroup key={track} label={label}>{items.map((level) => <option key={level.id} value={level.id}>{level.name}</option>)}</optgroup> : null;
      })}
    </select></label>
    {!rows.length ? <p className="muted-copy">No expectations defined for this level yet.</p> : <div className="kx-level-columns" aria-label={`${chosen?.name || "Selected level"} expectations`}>
      <section><h3>Knowledge</h3><ExpectationText rows={rows} field="expectation" empty="No knowledge expectation recorded for this level." /></section>
      <section><h3>Practical Skills</h3><ExpectationText rows={rows} field="practical_capability" empty="No practical skills recorded for this level." /></section>
    </div>}
  </div>;
}

function RelatedTopics({ related, onSelectTopic }) {
  const groups = useRelatedGroups(related);
  return <div className="kx-related">{groups.map(([label, items]) => <section key={label}><span className="field-label">{label}</span><ul>{items.map((item) => <li key={`${item.direction}-${item.relationship_type}-${item.id}`}><button type="button" className="text-link" onClick={() => onSelectTopic(item.topic_key)}>{item.name}</button></li>)}</ul></section>)}</div>;
}

function placementLabel(placement) {
  return [...placement.domain_path.map((domain) => domain.name), placement.label, ...(placement.ancestors || []).map((topic) => topic.name)].join(" › ");
}

export default function KnowledgeMapTopicPanel({ node, breadcrumb, placements, isCurrentPlacement, onReveal, onSelectTopic, onNavigate }) {
  const [detail, setDetail] = useState({ loading: true, error: null, topic: null });
  const [tab, setTab] = useState("overview");
  const [attempt, setAttempt] = useState(0);
  const tabRefs = useRef({});
  const baseId = useId();

  useEffect(() => {
    let active = true;
    setDetail({ loading: true, error: null, topic: null });
    fetchKnowledgeContractTopic(node.topicKey)
      .then((topic) => active && setDetail({ loading: false, error: null, topic }))
      .catch((error) => active && setDetail({ loading: false, error, topic: null }));
    return () => { active = false; };
  }, [node.topicKey, attempt]);

  const sections = useMemo(() => sectionsByType(detail.topic), [detail.topic]);
  const tabs = useMemo(() => (detail.topic ? availableTabs(detail.topic, sections) : []), [detail.topic, sections]);
  const activeTab = tabs.some(([id]) => id === tab) ? tab : tabs[0]?.[0];

  function onTabKeyDown(event, index) {
    const moves = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1 };
    if (!(event.key in moves)) return;
    event.preventDefault();
    const next = tabs[(moves[event.key] + tabs.length) % tabs.length][0];
    setTab(next);
    tabRefs.current[next]?.focus();
  }

  function renderTab(id) {
    if (id === "career_levels") return <CareerLevels expectations={detail.topic.level_expectations || []} legacy={sections.career_level_guidance} />;
    if (id === "related") return <RelatedTopics related={detail.topic.related_topics} onSelectTopic={onSelectTopic} />;
    return <SectionContent section={sections[id]} sections={sections} collapsible />;
  }

  const current = placements.items.find((placement) => isCurrentPlacement(placement));
  const currentNote = current ? current.context_note : node.contextNote;
  return <div className="km-topic-panel">
    <p className="eyebrow">TOPIC</p>
    <h2>{node.label}</h2>
    <p className="km-topic-path">{breadcrumb.join(" › ")}</p>
    {currentNote && <div className="km-details-section km-context-note"><span className="field-label">In {current?.domain_path[current.domain_path.length - 1]?.name || "this domain"}</span><p>{currentNote}</p></div>}
    <div className="km-details-section">
      <span className="field-label">Appears in</span>
      {placements.loading ? <Loading label="Loading placements" /> : placements.error ? <p className="muted-copy">Placements could not be loaded: {placements.error.message}</p> : <ul className="km-placement-list">{placements.items.map((placement) => {
        const current = isCurrentPlacement(placement);
        return <li key={placementLabel(placement)}><button type="button" className={`text-link ${current ? "current" : ""}`} aria-current={current ? "location" : undefined} onClick={() => onReveal(placement)}>{placementLabel(placement)}</button>{placement.context_note && !current && <small className="km-placement-note">{placement.context_note}</small>}</li>;
      })}</ul>}
    </div>
    <div className="km-topic-actions">
      {node.placementCount > 1 && <Badge tone="blue">Mapped in {node.placementCount} domains</Badge>}
      {onNavigate && <button type="button" className="button button-secondary" onClick={() => onNavigate("knowledge-topic", node.topicKey)}>Open full topic page</button>}
    </div>
    {detail.loading ? <Loading label="Loading topic details" />
      : detail.error ? <ErrorState error={detail.error} onRetry={() => setAttempt((value) => value + 1)} />
        : !tabs.length ? <p className="km-details-copy">{detail.topic.description || node.description || "No learning content has been published for this topic yet."}</p>
          : <>
            <div className="km-topic-tabs" role="tablist" aria-label={`${node.label} sections`}>
              {tabs.map(([id, label], index) => <button type="button" role="tab" key={id} id={`${baseId}-tab-${id}`} ref={(element) => { tabRefs.current[id] = element; }} aria-selected={activeTab === id} aria-controls={`${baseId}-panel`} tabIndex={activeTab === id ? 0 : -1} className={activeTab === id ? "active" : ""} onClick={() => setTab(id)} onKeyDown={(event) => onTabKeyDown(event, index)}>{label}</button>)}
            </div>
            <div className="km-topic-tabpanel knowledge-rich" role="tabpanel" id={`${baseId}-panel`} aria-labelledby={`${baseId}-tab-${activeTab}`} tabIndex={0}>{renderTab(activeTab)}</div>
          </>}
  </div>;
}
