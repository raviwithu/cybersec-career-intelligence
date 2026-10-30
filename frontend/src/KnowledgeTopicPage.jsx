import { useEffect, useMemo, useState } from "react";

import { fetchKnowledgeContractTopic, fetchKnowledgeContractTopics } from "./api";
import { Badge, EmptyState, ErrorState, Loading, PageHeader } from "./components";
import { SectionContent, sectionsByType } from "./KnowledgeSections";

const labels = {
  overview: "Overview",
  how_it_works: "How It Works",
  attack_surfaces: "Attack Surfaces",
  mitigations: "Mitigations",
  real_world_examples: "Real-World Examples",
  references: "References",
  career_level_guidance: "Career Guidance",
  code_examples: "Example Code",
  architecture: "Architecture",
};
const tabs = ["overview", "how_it_works", "code_examples", "attack_surfaces", "mitigations", "real_world_examples", "architecture", "references", "career_level_guidance"];

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
  const sections = useMemo(() => sectionsByType(topic), [topic]);
  if (loading) return <Loading label="Loading published knowledge topic" />;
  if (error) return <ErrorState error={error} />;
  if (!topic) return <EmptyState title="No published knowledge topics" message="Administrators must publish a topic before it appears here." />;
  const visibleTabs = tabs.filter((id) => sections[id]);
  const activeSection = sections[tab] || sections.overview || topic.sections[0];
  return <>
    <PageHeader eyebrow="KNOWLEDGE BASE" title={topic.name} description={topic.description || "Published, reviewed cybersecurity knowledge."}><div className="review-card-actions"><Badge tone="mint">Published v{activeSection?.published_version || 1}</Badge>{onNavigate && <button className="button button-secondary" onClick={() => onNavigate("knowledge-topics")}>Knowledge management</button>}</div></PageHeader>
    {topics.length > 1 && <label className="knowledge-topic-picker">Topic<select value={topic.topic_key} onChange={(event) => onNavigate?.("knowledge-topic", event.target.value)}>{topics.map((item) => <option key={item.topic_key} value={item.topic_key}>{item.name}</option>)}</select></label>}
    <section className="panel knowledge-topic-page"><div className="knowledge-topic-tabs" role="tablist" aria-label="Knowledge topic sections">{visibleTabs.map((id) => <button type="button" role="tab" aria-selected={tab === id} className={tab === id ? "active" : ""} key={id} onClick={() => setTab(id)}>{labels[id]}</button>)}</div>{activeSection ? <div className="knowledge-topic-section"><div className="panel-title-row"><div><p className="eyebrow">PUBLISHED KNOWLEDGE</p><h2>{labels[activeSection.section_type]}</h2></div><span className="muted-copy">Updated {new Date(activeSection.updated_at).toLocaleDateString()}</span></div><SectionContent section={activeSection} sections={sections} /></div> : <EmptyState title="Section not published" message="This topic has no published content for the selected section." />}</section>
    <section className="knowledge-coverage-summary"><div><span className="field-label">Coverage</span><strong>{topic.coverage.items.filter((item) => item.status === "published").length} / {topic.coverage.items.length} sections published</strong></div>{topic.coverage.items.filter((item) => item.status !== "published").map((item) => <Badge key={item.section_type} tone="amber">{labels[item.section_type]} not published</Badge>)}</section>
    {topic.related_topics?.length > 0 && <section className="panel related-topics"><p className="eyebrow">RELATED TOPICS</p><div className="tag-list">{topic.related_topics.map((item) => <button type="button" className="text-link" key={item.id} onClick={() => onNavigate?.("knowledge-topic", item.topic_key)}>{item.name}</button>)}</div></section>}
  </>;
}
