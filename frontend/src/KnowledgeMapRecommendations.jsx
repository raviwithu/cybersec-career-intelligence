import { useEffect, useState } from "react";

import { fetchRecommendationOptions, requestBranchRecommendations, submitBranchRecommendations } from "./api";
import { Badge, ErrorState, Loading } from "./components";
import { BRANCHES } from "./knowledgeMapModel";

// Recommendations for the three branches of any topic directly under a domain, filled or empty, from the RAG knowledge
// DB, Kimi, or RAG checked by Kimi. Nothing is stored until the administrator sends the selected ones to review, and
// nothing here can approve or publish.

const KIND = { update_description: "Update description", add_topic: "New topic" };
const STATUS = { connected: "Connected", unavailable: "Unavailable", unconfigured: "Not configured" };
const VERIFICATION = { confirmed: "Kimi confirmed", corrected: "Kimi corrected", unchecked: "Not checked by Kimi", kimi_only: "Kimi only, no RAG source" };
const SUBMIT_KEYS = ["kind", "ref", "expected_version", "branch", "name", "current_description", "description", "aliases", "weak", "sources", "verification", "verification_note"];

const topicKey = (topic) => `${topic.domain_id}:${topic.topic_id}`;
const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;

export default function KnowledgeMapRecommendations({ adminKey, onSubmitted }) {
  const [options, setOptions] = useState({ loading: true, error: null, sources: [], topics: [] });
  const [chosen, setChosen] = useState("");
  const [source, setSource] = useState("");
  const [ragDomain, setRagDomain] = useState("");
  const [result, setResult] = useState(null);
  const [selected, setSelected] = useState([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState("");

  function load() {
    setOptions((current) => ({ ...current, loading: true, error: null }));
    fetchRecommendationOptions(adminKey).then((data) => setOptions({ loading: false, error: null, ...data })).catch((requestError) => setOptions({ loading: false, error: requestError, sources: [], topics: [] }));
  }
  useEffect(load, [adminKey]);

  const topic = options.topics.find((item) => topicKey(item) === chosen);
  const rag = options.sources.find((item) => item.id === "rag");
  const ready = topic && options.sources.find((item) => item.id === source)?.status === "connected";

  function clear() { setResult(null); setSelected([]); setError(null); setNotice(""); }
  function chooseTopic(value) {
    clear();
    setChosen(value);
    setRagDomain(options.topics.find((item) => topicKey(item) === value)?.rag_domain || "");
  }
  function chooseSource(value) { clear(); setSource(value); }

  const usesRag = source === "rag" || (source === "both" && rag?.status === "connected");
  const request = () => ({ domain_id: topic.domain_id, source, ...(usesRag && ragDomain ? { rag_domain: ragDomain } : {}) });

  async function ask() {
    clear();
    setBusy("ask");
    try { setResult(await requestBranchRecommendations(topic.topic_id, request(), adminKey)); } catch (requestError) { setError(requestError); } finally { setBusy(""); }
  }

  async function submit() {
    setBusy("submit"); setError(null); setNotice("");
    try {
      const items = selected.map((index) => Object.fromEntries(SUBMIT_KEYS.map((key) => [key, result.recommendations[index][key]])));
      const response = await submitBranchRecommendations(topic.topic_id, { ...request(), items }, adminKey);
      const sent = new Set(response.done.map((position) => selected[position]));
      setResult({ ...result, recommendations: result.recommendations.filter((_, index) => !sent.has(index)) });
      setSelected([]);
      setNotice(`${plural(response.proposals.length, "proposal")} sent to review (${response.proposals.map((item) => `#${item.id}`).join(", ")}).${response.errors.length ? ` Not sent: ${response.errors.join(" ")}` : ""}`);
      onSubmitted?.();
      load();
    } catch (requestError) { setError(requestError); } finally { setBusy(""); }
  }

  const toggle = (index) => setSelected((current) => (current.includes(index) ? current.filter((value) => value !== index) : [...current, index]));

  return <section className="panel kma-suggestions" aria-label="Branch recommendations">
    <p className="eyebrow">BRANCH RECOMMENDATIONS</p>
    <h2>Get recommendations for a topic</h2>
    <p className="muted-copy">For any topic directly under a domain, even with empty branches. Covers Foundations, Security and Common Vulnerabilities, and each vulnerability comes with an example. Recommendations are not stored; the ones you select go to Knowledge Review. Nothing is approved or published here.</p>
    {options.loading && !options.topics.length ? <Loading label="Checking sources and topics" /> : options.error ? <ErrorState error={options.error} onRetry={load} /> : options.topics.length === 0 ? <p className="muted-copy">No published topic sits directly under a domain yet.</p> : <div className="kma-form">
      <label>Topic<select value={chosen} onChange={(event) => chooseTopic(event.target.value)}><option value="">Choose a topic</option>{options.topics.map((item) => <option key={topicKey(item)} value={topicKey(item)}>{item.domain_name} › {item.topic_name} ({item.counts.foundations} / {item.counts.security} / {item.counts.vulnerabilities})</option>)}</select></label>
      <fieldset className="kma-sources">
        <legend className="field-label">Connect to</legend>
        {options.sources.map((item) => <label key={item.id} className={`kma-source${item.status === "connected" ? "" : " kma-source-off"}`}>
          <input type="radio" name="recommendation-source" value={item.id} checked={source === item.id} disabled={item.status !== "connected"} onChange={() => chooseSource(item.id)} />
          <span><strong>{item.label}</strong> <Badge tone={item.status === "connected" ? "violet" : undefined}>{STATUS[item.status] || item.status}</Badge><small>{item.detail}</small></span>
        </label>)}
      </fieldset>
      {usesRag && <label>RAG domain<select value={ragDomain} onChange={(event) => { clear(); setRagDomain(event.target.value); }}><option value="">All domains</option>{rag.domains.map((item) => <option key={item.slug} value={item.slug}>{item.name} ({item.indexed_pct}% indexed)</option>)}</select></label>}
      <button type="button" className="button button-secondary" disabled={!ready || Boolean(busy)} onClick={ask}>{busy === "ask" ? "Asking…" : "Get recommendations"}</button>
    </div>}
    {busy === "ask" && <Loading label={`Waiting for recommendations. This can take ${source === "both" ? "up to 8" : "2 to 3"} minutes`} />}
    {error && <p className="kma-error" role="alert">{error.message}</p>}
    {notice && <p className="success-copy" role="status">{notice}</p>}
    {result && <div className="kma-suggestion-list">
      <p className="muted-copy">Source: {result.source_label}</p>
      {result.recommendations.length ? <ul>{result.recommendations.map((item, index) => <li key={`${item.kind}:${item.ref || item.name}`}><label className="kma-suggestion">
        <input type="checkbox" checked={selected.includes(index)} onChange={() => toggle(index)} aria-label={`Select ${KIND[item.kind]}: ${item.name}`} />
        <span><strong>{item.name}</strong> <Badge tone="violet">{KIND[item.kind]}</Badge> <Badge>{BRANCHES[item.branch]?.label || item.branch}</Badge>{item.weak && <> <Badge>Weak evidence</Badge></>}{item.verification && <> <Badge tone={item.verification === "confirmed" ? "violet" : undefined}>{VERIFICATION[item.verification]}</Badge></>}
          <span className="kma-compare">{item.current_description && <small><s>{item.current_description}</s></small>}<small>{item.description}</small></span>
          {item.verification_note && <small>Kimi: {item.verification_note}</small>}
          {item.sources.length > 0 && <small>Sources: {item.sources.map((entry) => `${entry.title}${entry.locator ? ` (${entry.locator})` : ""}`).join("; ")}</small>}
        </span>
      </label></li>)}</ul> : <p className="muted-copy">No recommendations left for this topic.</p>}
      {result.warnings.length > 0 && <details><summary>{plural(result.warnings.length, "note")}</summary><ul>{result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></details>}
      {result.recommendations.length > 0 && <button type="button" className="button" disabled={!selected.length || Boolean(busy)} onClick={submit}>{busy === "submit" ? "Sending…" : `Send ${selected.length || ""} selected to review`}</button>}
    </div>}
  </section>;
}
