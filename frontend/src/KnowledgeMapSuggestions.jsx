import { useEffect, useState } from "react";

import { fetchApprovedFindings, requestMapSuggestions, submitMapSuggestions } from "./api";
import { Badge, ErrorState, Loading } from "./components";
import { BRANCHES } from "./knowledgeMapModel";

// AI suggestions for an approved research finding. The model's output is shown for selection only; nothing is stored
// until the administrator submits the selected suggestions, which become "ai" proposals for normal review.

const SCHEMA_KEYS = ["action", "existing_topic_id", "name", "domain_id", "map_branch", "rationale", "related_topic_id", "relationship_type"];
const ACTIONS = { PLACE_TOPIC: "Place existing topic", CREATE_TOPIC: "Create topic (name and placement only)", ADD_TOPIC_RELATIONSHIP: "Add relationship" };

function describe(item) {
  if (item.action === "CREATE_TOPIC") return item.name;
  if (item.action === "ADD_TOPIC_RELATIONSHIP") return `${item.topic_name} ${item.relationship_type.replaceAll("_", " ")} ${item.related_topic_name}`;
  return item.topic_name;
}

export default function KnowledgeMapSuggestions({ adminKey, onSubmitted }) {
  const [findings, setFindings] = useState({ loading: true, error: null, items: [] });
  const [findingId, setFindingId] = useState("");
  const [result, setResult] = useState(null);
  const [selected, setSelected] = useState([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    fetchApprovedFindings(adminKey).then((items) => setFindings({ loading: false, error: null, items })).catch((requestError) => setFindings({ loading: false, error: requestError, items: [] }));
  }, [adminKey]);

  async function suggest() {
    setBusy("suggest"); setError(null); setNotice(""); setResult(null); setSelected([]);
    try { setResult(await requestMapSuggestions(findingId, adminKey)); } catch (requestError) { setError(requestError); } finally { setBusy(""); }
  }

  async function submit() {
    setBusy("submit"); setError(null); setNotice("");
    try {
      const chosen = selected.map((index) => Object.fromEntries(SCHEMA_KEYS.map((key) => [key, result.suggestions[index][key] ?? null])));
      const response = await submitMapSuggestions(findingId, chosen, adminKey);
      setNotice(`${response.created.length} ${response.created.length === 1 ? "proposal" : "proposals"} submitted for review (${response.created.map((item) => `#${item.id}`).join(", ")}).${response.errors.length ? ` Not submitted: ${response.errors.join(" ")}` : ""}`);
      setSelected([]);
      onSubmitted?.();
    } catch (requestError) { setError(requestError); } finally { setBusy(""); }
  }

  const toggle = (index) => setSelected((current) => (current.includes(index) ? current.filter((value) => value !== index) : [...current, index]));

  return <section className="panel kma-suggestions" aria-label="AI map suggestions">
    <p className="eyebrow">AI MAP SUGGESTIONS</p>
    <h2>Suggest map changes from a research finding</h2>
    <p className="muted-copy">Uses the configured AI model on a finding approved in Research Review. Suggestions are not stored; the ones you select become AI proposals for normal review. Job-description evidence supports placement only, never technical content.</p>
    {findings.loading ? <Loading label="Loading approved findings" /> : findings.error ? <ErrorState error={findings.error} /> : findings.items.length === 0 ? <p className="muted-copy">No approved research findings yet.</p> : <div className="kma-form">
      <label>Approved finding<select value={findingId} onChange={(event) => { setFindingId(event.target.value); setResult(null); setSelected([]); }}><option value="">Choose a finding</option>{findings.items.map((item) => <option key={item.id} value={item.id}>#{item.id} {item.candidate_name}{item.domain ? ` · ${item.domain}` : ""}</option>)}</select></label>
      <button type="button" className="button button-secondary" disabled={!findingId || Boolean(busy)} onClick={suggest}>{busy === "suggest" ? "Asking the model…" : "Suggest map changes"}</button>
    </div>}
    {busy === "suggest" && <Loading label="Waiting for the AI model" />}
    {error && <p className="kma-error" role="alert">{error.message}</p>}
    {notice && <p className="success-copy" role="status">{notice}</p>}
    {result && <div className="kma-suggestion-list">
      <p className="muted-copy">Model: {result.provider} / {result.model_id}</p>
      {result.suggestions.length ? <ul>{result.suggestions.map((item, index) => <li key={index}><label className="kma-suggestion">
        <input type="checkbox" checked={selected.includes(index)} onChange={() => toggle(index)} aria-label={`Select ${ACTIONS[item.action]}: ${describe(item)}`} />
        <span><strong>{describe(item)}</strong> <Badge tone="violet">{ACTIONS[item.action]}</Badge><small>{item.domain_name} › {BRANCHES[item.map_branch]?.label || item.map_branch}</small><small>{item.rationale}</small>{item.note && <small className="kma-note">{item.note}</small>}</span>
      </label></li>)}</ul> : <p className="muted-copy">The model returned no usable suggestions.</p>}
      {result.warnings.length > 0 && <details><summary>{result.warnings.length} suggestions were dropped</summary><ul>{result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></details>}
      {result.suggestions.length > 0 && <button type="button" className="button" disabled={!selected.length || Boolean(busy)} onClick={submit}>{busy === "submit" ? "Submitting…" : `Submit ${selected.length || ""} selected as proposals`}</button>}
    </div>}
  </section>;
}
