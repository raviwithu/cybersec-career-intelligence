import { useState } from "react";

import KnowledgeDiagram from "./KnowledgeDiagram";
import { isRenderableDiagram } from "./knowledgeDiagramLayout";

// Structured editors for the code_examples and architecture sections. The backend schemas stay authoritative;
// these forms only make valid content easier to write and show a live preview.

export const CODE_LANGUAGES = ["python", "javascript", "typescript", "java", "go", "csharp", "c", "cpp", "rust", "php", "ruby", "http", "json", "yaml", "bash"];
const MAX_CODE_EXAMPLES = 6;
const MAX_CODE_LENGTH = 8000;
const EMPTY_EXAMPLE = { title: "", language: "python", vulnerable: "", secure: "", explanation: "", security_control: "" };
const DIAGRAM_TEMPLATE = {
  kind: "flow", title: "New diagram", variant: "neutral",
  nodes: [{ id: "client", label: "Client", type: "actor" }, { id: "api", label: "API", type: "service" }],
  edges: [{ from: "client", to: "api", label: "Request", order: 1 }],
  boundaries: [],
};

export function CodeExamplesEditor({ value, onChange }) {
  const items = value.items || [];
  const setItem = (index, patch) => onChange({ ...value, items: items.map((item, position) => (position === index ? { ...item, ...patch } : item)) });
  return <section className="kse-structured" aria-label="Code examples">
    {items.map((item, index) => <fieldset key={index} className="kse-item">
      <legend>Example {index + 1}</legend>
      <div className="review-edit-grid">
        <label>Title<input value={item.title} maxLength="200" onChange={(event) => setItem(index, { title: event.target.value })} /></label>
        <label>Language<select value={item.language} onChange={(event) => setItem(index, { language: event.target.value })}>{CODE_LANGUAGES.map((language) => <option key={language} value={language}>{language}</option>)}</select></label>
        <label>Security control<input value={item.security_control} maxLength="200" onChange={(event) => setItem(index, { security_control: event.target.value })} /></label>
      </div>
      <div className="kse-code-columns">
        <label>⚠ Vulnerable code<textarea className="kse-code" rows="8" maxLength={MAX_CODE_LENGTH} value={item.vulnerable} onChange={(event) => setItem(index, { vulnerable: event.target.value })} /></label>
        <label>✓ Secure code<textarea className="kse-code" rows="8" maxLength={MAX_CODE_LENGTH} value={item.secure} onChange={(event) => setItem(index, { secure: event.target.value })} /></label>
      </div>
      <label>Explanation<textarea rows="3" maxLength={MAX_CODE_LENGTH} value={item.explanation} onChange={(event) => setItem(index, { explanation: event.target.value })} /></label>
      <button type="button" className="text-link" onClick={() => onChange({ ...value, items: items.filter((_, position) => position !== index) })}>Remove example {index + 1}</button>
    </fieldset>)}
    <button type="button" className="button button-secondary" disabled={items.length >= MAX_CODE_EXAMPLES} onClick={() => onChange({ ...value, items: [...items, { ...EMPTY_EXAMPLE }] })}>Add code example{items.length >= MAX_CODE_EXAMPLES ? ` (limit ${MAX_CODE_EXAMPLES})` : ""}</button>
  </section>;
}

function DiagramEditor({ diagram, index, onChange, onRemove }) {
  const [text, setText] = useState(() => JSON.stringify(diagram, null, 2));
  const [problem, setProblem] = useState("");
  function update(next) {
    setText(next);
    try {
      const parsed = JSON.parse(next);
      if (!isRenderableDiagram(parsed)) { setProblem("Each node needs an id and label, ids must be unique, and every edge must connect existing nodes."); return; }
      setProblem("");
      onChange(parsed);
    } catch { setProblem("The diagram must be valid JSON."); }
  }
  return <fieldset className="kse-item">
    <legend>Diagram {index + 1}</legend>
    <label>Diagram definition<textarea className="kse-code" rows="12" value={text} onChange={(event) => update(event.target.value)} aria-invalid={Boolean(problem)} /></label>
    {problem ? <p className="kma-error" role="alert">{problem}</p> : <KnowledgeDiagram diagram={diagram} />}
    <button type="button" className="text-link" onClick={onRemove}>Remove diagram {index + 1}</button>
  </fieldset>;
}

export function ArchitectureEditor({ value, onChange }) {
  const diagrams = value.diagrams || [];
  return <section className="kse-structured" aria-label="Architecture diagrams">
    <p className="muted-copy">Fields: kind (architecture, sequence, trust_boundary, attack_path, flow), title, variant (vulnerable, secure, neutral), nodes [id, label, type, boundary], edges [from, to, label, order], boundaries [id, label]. Ids use lowercase letters, digits, - and _.</p>
    {diagrams.map((diagram, index) => <DiagramEditor key={index} index={index} diagram={diagram} onChange={(next) => onChange({ ...value, diagrams: diagrams.map((item, position) => (position === index ? next : item)) })} onRemove={() => onChange({ ...value, diagrams: diagrams.filter((_, position) => position !== index) })} />)}
    <button type="button" className="button button-secondary" onClick={() => onChange({ ...value, diagrams: [...diagrams, DIAGRAM_TEMPLATE] })}>Add diagram</button>
  </section>;
}
