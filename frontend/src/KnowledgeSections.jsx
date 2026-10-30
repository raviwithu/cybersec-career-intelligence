import { lazy, Suspense, useMemo, useState } from "react";

import { Badge } from "./components";
import KnowledgeDiagram, { DiagramNotice, VARIANT_LABELS } from "./KnowledgeDiagram";

// Section renderers shared by the Knowledge Base topic page and the knowledge map topic panel.
// All content is rendered as React text nodes (D7): no Markdown, no HTML injection.

const KnowledgeCodeBlock = lazy(() => import("./KnowledgeCodeBlock"));

const VERIFIED = new Set(["verified", "authoritative"]);
const VERIFICATION_LABELS = { unverified: "Unverified", verified: "Verified", authoritative: "Authoritative", ai_derived: "AI-derived", restricted: "Restricted", rejected: "Rejected" };

export function isHttpUrl(value) {
  if (typeof value !== "string") return false;
  try { return ["http:", "https:"].includes(new URL(value).protocol); } catch { return false; }
}

// External links open in a new tab without referrer or opener; the URL shows on hover and keyboard focus.
export function SafeLink({ href, children }) {
  if (!isHttpUrl(href)) return null;
  return <a className="safe-link" href={href} target="_blank" rel="noopener noreferrer" title={href}>{children}<span className="safe-link-url">{href}</span></a>;
}

export function TextList({ values }) {
  if (!values?.length) return null;
  return <ul>{values.map((value) => <li key={value}>{value}</li>)}</ul>;
}

function itemTitle(item, index) {
  return item.name || item.title || item.control || item.cve_identifier || `Entry ${index + 1}`;
}

export function ItemList({ items, fields, empty = "No published entries in this section yet." }) {
  if (!items?.length) return <p className="muted-copy">{empty}</p>;
  return <div className="knowledge-item-list">{items.map((item, index) => <article className="knowledge-item" key={`${itemTitle(item, index)}-${index}`}><h3>{itemTitle(item, index)}</h3>{fields.map(([key, label]) => item[key] ? <div key={key}><span className="field-label">{label}</span><p>{Array.isArray(item[key]) ? item[key].join(" · ") : item[key]}</p></div> : null)}<SafeLink href={item.reference}>Open reference ↗</SafeLink></article>)}</div>;
}

export function OverviewSection({ content, collapsible = false }) {
  const [showDetails, setShowDetails] = useState(false);
  const technical = content.technical_explanation && content.short_description ? content.technical_explanation : "";
  return <div className="knowledge-section-copy">
    <p>{content.short_description || content.technical_explanation || "This section has been published without a short description."}</p>
    {technical && (collapsible
      ? <><button type="button" className="text-link" aria-expanded={showDetails} onClick={() => setShowDetails((value) => !value)}>{showDetails ? "Hide technical details" : "Show technical details"}</button>{showDetails && <p>{technical}</p>}</>
      : <p>{technical}</p>)}
    <div className="knowledge-two-column">{content.key_concepts?.length ? <div><span className="field-label">Key concepts</span><TextList values={content.key_concepts} /></div> : null}{content.related_technologies?.length ? <div><span className="field-label">Related technologies</span><TextList values={content.related_technologies} /></div> : null}</div>
  </div>;
}

function VariantDiagrams({ diagrams }) {
  const [variant, setVariant] = useState("vulnerable");
  const shown = diagrams.filter((diagram) => diagram.variant === variant);
  return <section className="kd-variants" aria-label="Vulnerable and secure flows">
    <div className="kd-variant-toggle" role="group" aria-label="Diagram variant">{["vulnerable", "secure"].map((id) => <button type="button" key={id} aria-pressed={variant === id} className={variant === id ? "active" : ""} onClick={() => setVariant(id)}>{VARIANT_LABELS[id]}</button>)}</div>
    {shown.map((diagram, index) => <KnowledgeDiagram key={`${variant}-${index}`} diagram={diagram} />)}
  </section>;
}

export function HowItWorksSection({ content, architecture }) {
  const variants = architecture?.diagrams || [];
  const hasBoth = variants.some((diagram) => diagram.variant === "vulnerable") && variants.some((diagram) => diagram.variant === "secure");
  return <div className="knowledge-section-copy">
    <p>{content.workflow || content.architecture_explanation}</p>
    {content.architecture_explanation && content.workflow && <p>{content.architecture_explanation}</p>}
    {content.steps?.length ? <ol>{content.steps.map((step) => <li key={step}>{step}</li>)}</ol> : null}
    {/* The section editor's default is an empty diagram; that means "no diagram", not an invalid one. */}
    {content.diagram && !(Array.isArray(content.diagram.nodes) && content.diagram.nodes.length === 0) && <KnowledgeDiagram diagram={content.diagram} />}
    {content.diagram_hidden && <DiagramNotice />}
    {hasBoth && <VariantDiagrams diagrams={variants} />}
  </div>;
}

export function ArchitectureSection({ content }) {
  const diagrams = content.diagrams || [];
  return <div className="knowledge-section-copy">
    {diagrams.length ? diagrams.map((diagram, index) => <KnowledgeDiagram key={`${diagram.title}-${index}`} diagram={diagram} />) : !content.hidden_diagram_count && <p className="muted-copy">No architecture diagrams have been published.</p>}
    {content.hidden_diagram_count ? <DiagramNotice count={content.hidden_diagram_count} /> : null}
  </div>;
}

function CopyButton({ text, label }) {
  const [state, setState] = useState("");
  async function copy() {
    try { await navigator.clipboard.writeText(text); setState("Copied"); } catch { setState("Copy failed"); }
  }
  return <><button type="button" className="kc-copy" aria-label={`Copy ${label}`} onClick={copy}>Copy</button><span className="kc-copy-status" role="status">{state}</span></>;
}

function CodePane({ kind, code, language, title }) {
  const label = kind === "vulnerable" ? "Vulnerable" : "Secure";
  return <div className={`kc-pane kc-${kind}`}>
    <div className="kc-pane-header"><span className="kc-pane-label"><span aria-hidden="true">{kind === "vulnerable" ? "⚠" : "✓"}</span> {label}</span><CopyButton text={code} label={`${label.toLowerCase()} code for ${title}`} /></div>
    <Suspense fallback={<pre className="kc-code"><code>{code}</code></pre>}><KnowledgeCodeBlock code={code} language={language} /></Suspense>
  </div>;
}

export function CodeExamplesSection({ content }) {
  const items = content.items || [];
  if (!items.length) return <p className="muted-copy">No code examples have been published.</p>;
  return <div className="kc-list">{items.map((item, index) => <article className="kc-example" key={`${item.title}-${index}`}>
    <div className="kc-example-header"><h3>{item.title}</h3><Badge tone="blue">{item.language}</Badge></div>
    <div className="kc-panes">{item.vulnerable && <CodePane kind="vulnerable" code={item.vulnerable} language={item.language} title={item.title} />}{item.secure && <CodePane kind="secure" code={item.secure} language={item.language} title={item.title} />}</div>
    {item.explanation && <div><span className="field-label">Explanation</span><p>{item.explanation}</p></div>}
    {item.security_control && <div><span className="field-label">Security control</span><p>{item.security_control}</p></div>}
  </article>)}{content.hidden_item_count ? <p className="kd-notice" role="note">{content.hidden_item_count} code {content.hidden_item_count === 1 ? "example" : "examples"} could not be displayed.</p> : null}</div>;
}

// "Exploited in the wild" is shown only for verified items that say so; anything else is described conservatively.
export function exploitationLabel(item) {
  const status = String(item.exploitation_status || "").toLowerCase();
  if (status === "exploited_in_the_wild" && VERIFIED.has(item.verification_status)) return "Exploited in the wild";
  if (status === "proof_of_concept") return "Proof of concept";
  return "Publicly disclosed";
}

function Field({ label, value }) {
  if (!value) return null;
  return <div><span className="field-label">{label}</span><p>{Array.isArray(value) ? value.join(" · ") : value}</p></div>;
}

export function RealWorldExamplesSection({ content }) {
  const items = content.items || [];
  if (!items.length) return <p className="muted-copy">No verified real-world example has been added.</p>;
  return <div className="knowledge-item-list">{items.map((item, index) => {
    const identifier = item.cve_identifier || item.identifier;
    const title = item.advisory_or_research_title || item.title || item.name;
    const verified = VERIFIED.has(item.verification_status);
    return <article className="knowledge-item kx-cve" key={`${identifier || title || "example"}-${index}`}>
      <h3>{identifier || title || `Example ${index + 1}`}</h3>
      <div className="kx-badges"><Badge tone={exploitationLabel(item) === "Exploited in the wild" ? "violet" : "neutral"}>{exploitationLabel(item)}</Badge>{verified ? <Badge tone="mint">{VERIFICATION_LABELS[item.verification_status]}</Badge> : <Badge tone="neutral">Unverified</Badge>}</div>
      {identifier && title && <Field label="Advisory or research" value={title} />}
      <Field label="Affected product" value={item.affected_product || item.affected_component} />
      <Field label="Description" value={item.description || item.vulnerability_mechanism} />
      <Field label="Weakness" value={item.weakness || item.cwe} />
      <Field label="Impact" value={item.impact} />
      <Field label="Remediation" value={item.remediation} />
      <SafeLink href={item.reference || item.url}>Open reference ↗</SafeLink>
    </article>;
  })}</div>;
}

export function ReferencesSection({ content }) {
  const items = content.items || [];
  if (!items.length) return <p className="muted-copy">No public references have been published.</p>;
  return <div className="knowledge-item-list">{items.map((item, index) => <article className="knowledge-item" key={`${item.title || item.name}-${index}`}>
    <h3>{item.title || item.name || `Reference ${index + 1}`}</h3>
    <div className="kx-badges"><Badge tone={VERIFIED.has(item.verification_status) ? "mint" : "neutral"}>{VERIFICATION_LABELS[item.verification_status] || "Unverified"}</Badge>{item.source_type && <Badge tone="blue">{item.source_type.replaceAll("_", " ")}</Badge>}</div>
    <Field label="Author" value={item.author} />
    <Field label="Publisher" value={item.publisher} />
    <Field label="Publication date" value={item.publication_date} />
    <Field label="Version" value={item.document_version} />
    <Field label="Relevant section" value={item.locator} />
    <SafeLink href={item.url || item.reference}>Open source ↗</SafeLink>
  </article>)}</div>;
}

export function LegacyCareerGuidance({ content }) {
  return <div className="knowledge-guidance-grid">{Object.entries(content.levels || {}).filter(([, guidance]) => guidance).map(([level, guidance]) => <article className="knowledge-item" key={level}><Badge tone="violet">{level}</Badge><p>{guidance}</p></article>)}</div>;
}

export function sectionsByType(topic) {
  return Object.fromEntries((topic?.sections || []).map((section) => [section.section_type, section]));
}

export function SectionContent({ section, sections = {}, collapsible = false }) {
  const content = section.content || {};
  switch (section.section_type) {
    case "overview": return <OverviewSection content={content} collapsible={collapsible} />;
    case "how_it_works": return <HowItWorksSection content={content} architecture={sections.architecture?.content} />;
    case "attack_surfaces": return <ItemList items={content.items} fields={[["weakness_description", "Weakness"], ["attack_scenario", "Attack scenario"], ["potential_impact", "Potential impact"], ["related_vulnerability_classes", "Related vulnerability classes"]]} />;
    case "mitigations": return <ItemList items={content.items} fields={[["description", "Description"], ["applicable_attack_surfaces", "Applicable attack surfaces"], ["implementation_considerations", "Implementation considerations"], ["validation_guidance", "Validation guidance"]]} />;
    case "real_world_examples": return <RealWorldExamplesSection content={content} />;
    case "references": return <ReferencesSection content={content} />;
    case "code_examples": return <CodeExamplesSection content={content} />;
    case "architecture": return <ArchitectureSection content={content} />;
    default: return <LegacyCareerGuidance content={content} />;
  }
}

// Related topics grouped by their display label ("Prerequisite", "Used by", "Protects against", ...).
export function useRelatedGroups(related) {
  return useMemo(() => {
    const groups = new Map();
    (related || []).forEach((item) => {
      const label = item.label || item.relationship_type || "Related";
      if (!groups.has(label)) groups.set(label, []);
      groups.get(label).push(item);
    });
    return [...groups.entries()];
  }, [related]);
}
