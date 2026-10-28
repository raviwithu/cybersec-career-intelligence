import { useEffect, useMemo, useState } from "react";

import { fetchKnowledgeContractTopic, fetchKnowledgeContractTopics } from "./api";
import { Badge, EmptyState, ErrorState, Loading, PageHeader } from "./components";

const labels = {
  overview: "Overview",
  how_it_works: "How It Works",
  attack_surfaces: "Attack Surfaces",
  mitigations: "Mitigations",
  real_world_examples: "Real-World Examples",
  references: "References",
  career_level_guidance: "Career Guidance",
};
const tabs = ["overview", "how_it_works", "attack_surfaces", "mitigations", "real_world_examples", "references"];

function TextList({ values }) {
  if (!values?.length) return null;
  return <ul>{values.map((value) => <li key={value}>{value}</li>)}</ul>;
}

function ItemList({ items, fields }) {
  if (!items?.length) return <p className="muted-copy">No published entries in this section yet.</p>;
  return <div className="knowledge-item-list">{items.map((item, index) => <article className="knowledge-item" key={`${item.name || item.title || item.control || item.cve_identifier || "item"}-${index}`}><h3>{item.name || item.title || item.control || item.cve_identifier || `Entry ${index + 1}`}</h3>{fields.map(([key, label]) => item[key] ? <div key={key}><span className="field-label">{label}</span><p>{Array.isArray(item[key]) ? item[key].join(" · ") : item[key]}</p></div> : null)}{item.reference && <a href={item.reference} target="_blank" rel="noreferrer">Open reference ↗</a>}</article>)}</div>;
}

function SectionContent({ section }) {
  const content = section.content || {};
  if (section.section_type === "overview") return <div className="knowledge-section-copy"><p>{content.short_description || content.technical_explanation || "This section has been published without a short description."}</p>{content.technical_explanation && content.short_description && <p>{content.technical_explanation}</p>}<div className="knowledge-two-column">{content.key_concepts?.length ? <div><span className="field-label">Key concepts</span><TextList values={content.key_concepts} /></div> : null}{content.related_technologies?.length ? <div><span className="field-label">Related technologies</span><TextList values={content.related_technologies} /></div> : null}</div></div>;
  if (section.section_type === "how_it_works") return <div className="knowledge-section-copy"><p>{content.workflow || content.architecture_explanation}</p>{content.architecture_explanation && content.workflow && <p>{content.architecture_explanation}</p>}{content.steps?.length ? <ol>{content.steps.map((step) => <li key={step}>{step}</li>)}</ol> : null}{content.diagram && <div className="knowledge-diagram"><span className="field-label">Architecture diagram definition</span><pre>{JSON.stringify(content.diagram, null, 2)}</pre></div>}</div>;
  if (section.section_type === "attack_surfaces") return <ItemList items={content.items} fields={[["weakness_description", "Weakness"], ["attack_scenario", "Attack scenario"], ["potential_impact", "Potential impact"], ["related_vulnerability_classes", "Related vulnerability classes"]]} />;
  if (section.section_type === "mitigations") return <ItemList items={content.items} fields={[["description", "Description"], ["applicable_attack_surfaces", "Applicable attack surfaces"], ["implementation_considerations", "Implementation considerations"], ["validation_guidance", "Validation guidance"]]} />;
  if (section.section_type === "real_world_examples") return <ItemList items={content.items} fields={[["advisory_or_research_title", "Advisory or research"], ["affected_component", "Affected component"], ["vulnerability_mechanism", "Vulnerability mechanism"], ["impact", "Impact"], ["remediation", "Remediation"]]} />;
  if (section.section_type === "references") return <ItemList items={content.items} fields={[["source_type", "Source type"], ["publisher", "Publisher"], ["publication_date", "Publication date"], ["locator", "Relevant section"]]} />;
  return <div className="knowledge-guidance-grid">{Object.entries(content.levels || {}).map(([level, guidance]) => <article className="knowledge-item" key={level}><Badge tone="violet">{level}</Badge><p>{guidance}</p></article>)}</div>;
}

export default function KnowledgeTopicPage({ topicKey, onNavigate }) {
  const [topics, setTopics] = useState([]);
  const [topic, setTopic] = useState(null);
  const [tab, setTab] = useState("overview");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(null);
    const request = topicKey ? fetchKnowledgeContractTopic(topicKey) : fetchKnowledgeContractTopics();
    request.then((result) => { if (!active) return; if (Array.isArray(result)) { setTopics(result); setTopic(result[0] || null); } else setTopic(result); }).catch((requestError) => active && setError(requestError)).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [topicKey]);
  const sections = useMemo(() => Object.fromEntries((topic?.sections || []).map((section) => [section.section_type, section])), [topic]);
  if (loading) return <Loading label="Loading published knowledge topic" />;
  if (error) return <ErrorState error={error} />;
  if (!topic) return <EmptyState title="No published knowledge topics" message="Administrators must publish a topic before it appears here." />;
  const visibleTabs = tabs.filter((id) => sections[id]);
  const activeSection = sections[tab] || sections.overview || topic.sections[0];
  return <>
    <PageHeader eyebrow="KNOWLEDGE BASE" title={topic.name} description={topic.description || "Published, reviewed cybersecurity knowledge."}><div className="review-card-actions"><Badge tone="mint">Published v{activeSection?.published_version || 1}</Badge>{onNavigate && <button className="button button-secondary" onClick={() => onNavigate("knowledge-topics")}>Knowledge management</button>}</div></PageHeader>
    {topics.length > 1 && <label className="knowledge-topic-picker">Topic<select value={topic.topic_key} onChange={(event) => onNavigate?.("knowledge-topic", event.target.value)}>{topics.map((item) => <option key={item.topic_key} value={item.topic_key}>{item.name}</option>)}</select></label>}
    <section className="panel knowledge-topic-page"><div className="knowledge-topic-tabs" role="tablist" aria-label="Knowledge topic sections">{visibleTabs.map((id) => <button type="button" role="tab" aria-selected={tab === id} className={tab === id ? "active" : ""} key={id} onClick={() => setTab(id)}>{labels[id]}</button>)}</div>{activeSection ? <div className="knowledge-topic-section"><div className="panel-title-row"><div><p className="eyebrow">PUBLISHED KNOWLEDGE</p><h2>{labels[activeSection.section_type]}</h2></div><span className="muted-copy">Updated {new Date(activeSection.updated_at).toLocaleDateString()}</span></div><SectionContent section={activeSection} /></div> : <EmptyState title="Section not published" message="This topic has no published content for the selected section." />}</section>
    <section className="knowledge-coverage-summary"><div><span className="field-label">Coverage</span><strong>{topic.coverage.items.filter((item) => item.status === "published").length} / {topic.coverage.items.length} sections published</strong></div>{topic.coverage.items.filter((item) => item.status !== "published").map((item) => <Badge key={item.section_type} tone="amber">{labels[item.section_type]} not published</Badge>)}</section>
    {topic.related_topics?.length > 0 && <section className="panel related-topics"><p className="eyebrow">RELATED TOPICS</p><div className="tag-list">{topic.related_topics.map((item) => <button type="button" className="text-link" key={item.id} onClick={() => onNavigate?.("knowledge-topic", item.topic_key)}>{item.name}</button>)}</div></section>}
  </>;
}
