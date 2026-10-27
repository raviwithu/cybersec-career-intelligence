import { useEffect, useState } from "react";

import {
  approveResearchDraft,
  evaluateAIModels,
  fetchAIModels,
  testAIModel,
  selectAIModel,
  refreshAIModels,
  fetchResearchDrafts,
  fetchResearchSubmissions,
  fetchResearchReviewDashboard,
  deleteResearchSubmission,
  importResearchUrl,
  publishResearchDraft,
  rejectResearchDraft,
  submitResearchFile,
  submitResearchText,
  updateResearchDraft,
  clearAdminSessionKey,
  getAdminSessionKey,
  setAdminSessionKey,
} from "./api";
import { Badge, EmptyState, ErrorState, Loading, PageHeader } from "./components";

const emptyForm = { source_title: "", source_url: "", research_date: "", content: "" };

export default function ResearchAdminPage() {
  const [enteredKey, setEnteredKey] = useState(() => getAdminSessionKey());
  const [adminKey, setAdminKey] = useState(() => getAdminSessionKey());
  const [method, setMethod] = useState("paste");
  const [url, setUrl] = useState("");
  const [preview, setPreview] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [selectedFile, setSelectedFile] = useState(null);
  const [submissions, setSubmissions] = useState([]);
  const [drafts, setDrafts] = useState([]);
  const [models, setModels] = useState(null);
  const [pendingProvider, setPendingProvider] = useState("ollama");
  const [pendingModelId, setPendingModelId] = useState("");
  const [testResult, setTestResult] = useState(null);
  const [error, setError] = useState(null);
  const [importError, setImportError] = useState(null);
  const [submitError, setSubmitError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [edits, setEdits] = useState({});
  const [submissionToDelete, setSubmissionToDelete] = useState(null);
  const [pendingReviewCount, setPendingReviewCount] = useState(0);
  const [notice, setNotice] = useState(null);

  async function load() {
    if (!adminKey) return;
    setLoading(true); setError(null);
    try {
      const [modelCatalog, submissionPage, draftPage, reviewDashboard] = await Promise.all([
        fetchAIModels(adminKey), fetchResearchSubmissions(adminKey), fetchResearchDrafts("", adminKey), fetchResearchReviewDashboard({}, adminKey),
      ]);
      setModels(modelCatalog);
      setPendingReviewCount(reviewDashboard.pending_reviews?.length || 0);
      setPendingProvider(modelCatalog.active_provider || "ollama");
      setPendingModelId(modelCatalog.active_model_id || "");
      setSubmissions(submissionPage.items); setDrafts(draftPage.items);
    } catch (requestError) { setError(requestError); } finally { setLoading(false); }
  }
  useEffect(() => { if (adminKey) load(); }, [adminKey]);


  const providerCatalog = (models?.providers || []).find((item) => item.provider === pendingProvider);
  const pendingModels = providerCatalog?.models || [];

  async function refreshModels() {
    setSaving(true); setError(null);
    try {
      const result = await refreshAIModels(adminKey);
      setModels(result); setPendingProvider(result.active_provider || "ollama"); setPendingModelId(result.active_model_id || "");
    } catch (requestError) { setError(requestError); } finally { setSaving(false); }
  }

  async function evaluateModels() {
    setSaving(true); setError(null);
    try {
      const result = await evaluateAIModels(adminKey);
      setModels(result); setPendingProvider(result.active_provider || "ollama"); setPendingModelId(result.active_model_id || "");
    } catch (requestError) { setError(requestError); } finally { setSaving(false); }
  }

  async function selectModel(event) {
    event.preventDefault(); if (!pendingModelId) return;
    setSaving(true); setError(null);
    try {
      const result = await selectAIModel(pendingProvider, pendingModelId, adminKey);
      setModels(result);
    } catch (requestError) { setError(requestError); } finally { setSaving(false); }
  }

  async function testModel() {
    if (!pendingModelId) return;
    setSaving(true); setError(null); setTestResult(null);
    try { setTestResult(await testAIModel(pendingProvider, pendingModelId, adminKey)); }
    catch (requestError) { setError(requestError); } finally { setSaving(false); }
  }

  async function submitText(event) {
    event.preventDefault(); setSaving(true); setError(null); setSubmitError(null);
    try {
      const result = await submitResearchText({ ...form, content: form.content.trim(), research_date: form.research_date || null, source_type: method === "url" && preview ? "url_imported" : "pasted_text" }, adminKey);
      // The API records provider failures as a "failed" submission; keep the form so it can be retried.
      if (result.status === "failed") { setSubmitError(new Error(result.error_message || "The AI provider could not analyze this content.")); await load(); return; }
      setForm(emptyForm); setPreview(null); setUrl(""); await load();
    } catch (requestError) { setSubmitError(requestError); } finally { setSaving(false); }
  }

  async function submitFile(event) {
    event.preventDefault(); if (!selectedFile) return;
    setSaving(true); setError(null); setSubmitError(null);
    try {
      const data = new FormData(); data.append("file", selectedFile);
      if (form.source_title) data.append("source_title", form.source_title);
      if (form.source_url) data.append("source_url", form.source_url);
      if (form.research_date) data.append("research_date", form.research_date);
      const result = await submitResearchFile(data, adminKey);
      if (result.status === "failed") { setSubmitError(new Error(result.error_message || "The AI provider could not analyze this file.")); await load(); return; }
      setSelectedFile(null); event.target.reset(); await load();
    } catch (requestError) { setSubmitError(requestError); } finally { setSaving(false); }
  }

  async function fetchUrlPreview(event) {
    event.preventDefault(); setSaving(true); setImportError(null); setPreview(null);
    try {
      const result = await importResearchUrl(url.trim(), adminKey);
      setPreview(result);
      setForm({ source_title: result.job_title, source_url: result.source_url, research_date: result.date_posted ? result.date_posted.slice(0, 10) : "", content: result.job_description });
    } catch (requestError) { setImportError(requestError); } finally { setSaving(false); }
  }


  async function removeSubmission() {
    if (!submissionToDelete) return;
    setSaving(true); setError(null); setNotice(null);
    try {
      await deleteResearchSubmission(submissionToDelete.id, adminKey);
      setSubmissionToDelete(null);
      setNotice("Research submission deleted successfully.");
      await load();
    } catch (requestError) {
      setError(requestError);
    } finally {
      setSaving(false);
    }
  }

  const activeProviderLabel = models?.active_provider === "openwebui" ? "OpenWebUI" : "Ollama";
  const activeCatalog = models?.providers?.find((provider) => provider.provider === models.active_provider);
  const activeModelMissing = activeCatalog?.status === "connected" && !activeCatalog.models.some((model) => model.id === models.active_model_id);
  const submitErrorNote = <>{activeModelMissing && !submitError && <p className="error-copy" role="alert">The active model "{models.active_model_id}" is not offered by {activeProviderLabel}. Select another model above before analyzing.</p>}{submitError && <p className="error-copy" role="alert">Analysis failed: {submitError.message}</p>}</>;

  function editValue(draft, field) { return edits[draft.id]?.[field] ?? draft[field]; }
  function setEdit(draft, field, value) { setEdits((current) => ({ ...current, [draft.id]: { ...current[draft.id], [field]: value } })); }
  async function update(draft) {
    setSaving(true); setError(null);
    try {
      await updateResearchDraft(draft.id, {
        expectation_description: editValue(draft, "expectation_description"), proficiency_level: editValue(draft, "proficiency_level"),
        importance: editValue(draft, "importance"), responsibility_type: editValue(draft, "responsibility_type"),
        experience_years_min: editValue(draft, "experience_years_min") === "" ? null : Number(editValue(draft, "experience_years_min")),
        experience_years_max: editValue(draft, "experience_years_max") === "" ? null : Number(editValue(draft, "experience_years_max")),
        reviewer_note: editValue(draft, "reviewer_note") || null,
      }, adminKey); await load();
    } catch (requestError) { setError(requestError); } finally { setSaving(false); }
  }
  async function review(draft, action) {
    setSaving(true); setError(null);
    try {
      if (action === "approve") await approveResearchDraft(draft.id, editValue(draft, "reviewer_note") || null, adminKey);
      if (action === "reject") await rejectResearchDraft(draft.id, editValue(draft, "reviewer_note") || null, adminKey);
      if (action === "publish") await publishResearchDraft(draft.id, adminKey);
      await load();
    } catch (requestError) { setError(requestError); } finally { setSaving(false); }
  }

  if (!adminKey) return <><PageHeader eyebrow="PHASE 5 / ADMIN" title="Research consolidation" description="Submit job descriptions, review AI findings, and publish only approved expectations into the public competency taxonomy." /><section className="panel research-auth"><p className="eyebrow">ADMINISTRATOR ACCESS</p><h2>Unlock the research console</h2><p className="muted-copy">Enter the server-configured administrator key. It stays in this browser session only and is cleared when you lock the console or close the browser session.</p><input aria-label="Administrator API key" type="password" placeholder="X-Admin-API-Key" value={enteredKey} onChange={(event) => setEnteredKey(event.target.value)} /><button className="button" disabled={!enteredKey} onClick={() => { setAdminSessionKey(enteredKey); setAdminKey(enteredKey); }}>Open research console</button></section></>;

  return <>
    <PageHeader eyebrow="PHASE 5 / ADMIN" title="Research consolidation" description="Analyze untrusted job-description text through the selected AI provider, map findings to the existing taxonomy, and review evidence before publication."><button className="button button-secondary" onClick={() => { clearAdminSessionKey(); setAdminKey(""); setEnteredKey(""); setModels(null); setTestResult(null); }}>Lock console</button></PageHeader>
    {error && <ErrorState error={error} onRetry={load} />}
    {notice && <p className="success-copy" role="status">{notice}</p>}
    <div className="research-status-row"><Badge tone={models?.providers?.some((item) => item.status === "connected") ? "mint" : "amber"}>AI providers · {models ? "checked" : "checking"}</Badge><span className="muted-copy">Active: {models?.active_provider || "—"} → {models?.active_model_name || models?.active_model_id || "—"} · {models?.mode || "fallback"}</span><button className="button button-secondary" onClick={load}>Refresh workflow</button></div>
    <section className="panel model-panel"><div className="panel-title-row"><div><p className="eyebrow">AI MODEL CONFIGURATION</p><h2>Ollama + OpenWebUI</h2></div><Badge tone={models?.mode === "automatic" ? "mint" : "violet"}>{models?.mode || "fallback"}</Badge></div><p className="muted-copy">Models are discovered dynamically through each provider. Routes that look like duplicates remain separate because OpenWebUI may apply different settings or external routing.</p><div className="model-provider-grid">{(models?.providers || []).map((provider) => <article className="model-provider-card" key={provider.provider}><div className="panel-title-row"><h3>{provider.provider}</h3><Badge tone={provider.status === "connected" ? "mint" : "amber"}>{provider.status}</Badge></div>{provider.error && <p className="error-copy">{provider.error}</p>}{provider.models.map((model) => <button type="button" className={`model-option ${pendingProvider === provider.provider && pendingModelId === model.id ? "selected" : ""}`} key={`${provider.provider}-${model.id}`} onClick={() => { setPendingProvider(provider.provider); setPendingModelId(model.id); }}><span><strong>{model.name}</strong><small>{model.id}{model.provider_info ? ` · ${model.provider_info}` : ""}</small></span><span>{model.possible_duplicate ? <Badge tone="violet">Possible duplicate</Badge> : <Badge>Available</Badge>}</span></button>)}{provider.status === "connected" && !provider.models.length && <p className="muted-copy">No models returned by this provider.</p>}</article>)}</div><form className="model-toolbar" onSubmit={selectModel}><label>Provider<select aria-label="AI provider" value={pendingProvider} onChange={(event) => { setPendingProvider(event.target.value); setPendingModelId(""); }}><option value="ollama">Ollama</option><option value="openwebui">OpenWebUI</option></select></label><label>Model<select aria-label="Installed Ollama model" value={pendingModelId} onChange={(event) => setPendingModelId(event.target.value)}><option value="" disabled>Select a discovered model</option>{pendingModelId && !pendingModels.some((model) => model.id === pendingModelId) && <option value={pendingModelId}>Current selection · {pendingModelId}</option>}{pendingModels.map((model) => <option key={model.id} value={model.id}>{model.name} · {model.id}</option>)}</select></label><button className="button button-secondary" disabled={saving || !pendingModelId}>Use selected model</button><button type="button" className="button button-secondary" disabled={saving} onClick={testModel}>Test model</button><button type="button" className="button button-secondary" disabled={saving} onClick={refreshModels}>Refresh Models</button><button type="button" className="button" disabled={saving} onClick={evaluateModels}>Evaluate Models</button></form>{testResult && <p className={testResult.reachable ? "success-copy" : "error-copy"}>{testResult.detail}{testResult.latency_ms ? ` · ${testResult.latency_ms} ms` : ""}</p>}{models?.evaluations?.length > 0 && <div className="model-evaluations"><h3>Evaluation results by provider</h3><p className="muted-copy">This small benchmark informs administrator choice; it does not establish an objectively best model.</p><div className="table-wrap"><table><thead><tr><th>Provider</th><th>Model ID</th><th>Extraction</th><th>Domain</th><th>Career level</th><th>JSON valid</th><th>Hallucination</th><th>Avg ms</th><th>Overall</th></tr></thead><tbody>{models.evaluations.map((evaluation) => <tr key={`${evaluation.provider}-${evaluation.model_id}-${evaluation.evaluation_version}`}><td>{evaluation.provider}</td><td>{evaluation.model_id || evaluation.model_name}{evaluation.error_message && <small className="error-copy">{evaluation.error_message}</small>}</td><td>{(evaluation.extraction_accuracy * 100).toFixed(1)}%</td><td>{(evaluation.domain_accuracy * 100).toFixed(1)}%</td><td>{(evaluation.career_level_accuracy * 100).toFixed(1)}%</td><td>{(evaluation.json_validity * 100).toFixed(1)}%</td><td>{(evaluation.hallucination_rate * 100).toFixed(1)}%</td><td>{evaluation.average_processing_ms.toFixed(0)}</td><td><strong>{(evaluation.overall_score * 100).toFixed(1)}%</strong></td></tr>)}</tbody></table></div></div>}</section>
    <div className="research-layout">
      <section className="panel"><p className="eyebrow">NEW SOURCE</p><h2>Submit research</h2><p className="muted-copy">Choose one input method. URL imports are preview-only until you explicitly analyze the editable content.</p>
        <div className="research-methods" role="tablist" aria-label="Research input method"><button type="button" className={method === "paste" ? "active" : ""} onClick={() => { setMethod("paste"); setSubmitError(null); }}>Paste Description</button><button type="button" className={method === "file" ? "active" : ""} onClick={() => { setMethod("file"); setSubmitError(null); }}>Upload File</button><button type="button" className={method === "url" ? "active" : ""} onClick={() => { setMethod("url"); setSubmitError(null); }}>Import from URL</button></div>
        {method === "paste" && <form className="research-form" onSubmit={submitText}><label>Source title<input value={form.source_title} onChange={(event) => setForm({ ...form, source_title: event.target.value })} placeholder="Cloud security role brief" /></label><label>Source URL<input value={form.source_url} onChange={(event) => setForm({ ...form, source_url: event.target.value })} placeholder="https://…" /></label><label>Research date<input type="date" value={form.research_date} onChange={(event) => setForm({ ...form, research_date: event.target.value })} /></label><label>Job description<textarea required rows="9" value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} placeholder="Paste untrusted research text here…" /></label><button className="button" disabled={saving}>{saving ? "Analyzing…" : "Analyze pasted text"}</button>{submitErrorNote}</form>}
        {method === "file" && <form className="upload-form" onSubmit={submitFile}><label>Research file<input type="file" accept=".txt,.json,.csv,text/plain,application/json,text/csv" onChange={(event) => setSelectedFile(event.target.files?.[0] || null)} /></label><button className="button button-secondary" disabled={saving || !selectedFile}>{saving ? "Processing…" : "Analyze file"}</button>{submitErrorNote}</form>}
        {method === "url" && <><form className="research-form" onSubmit={fetchUrlPreview}><label>Job Posting URL<input aria-label="Job Posting URL" required type="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://company.example/careers/security-engineer" /></label><button className="button button-secondary" disabled={saving || !url.trim()}>{saving ? "Fetching…" : "Fetch Job Description"}</button></form>{importError && <p className="error-copy" role="alert">{importError.message}</p>}{preview && <form className="url-preview" onSubmit={submitText}><div className="preview-banner"><Badge tone="mint">Preview ready · {preview.extraction_method}</Badge><a href={preview.source_url} target="_blank" rel="noreferrer">Original source ↗</a></div><label>Extracted job title<input value={form.source_title} onChange={(event) => setForm({ ...form, source_title: event.target.value })} required /></label><label>Source URL<input value={form.source_url} readOnly /></label><label>Date posted<input type="date" value={form.research_date} onChange={(event) => setForm({ ...form, research_date: event.target.value })} /></label><label>Editable job description<textarea required rows="12" value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} /></label><p className="muted-copy">Review and correct the extracted content before sending it to the active provider.</p><button className="button" disabled={saving}>{saving ? "Analyzing…" : `Analyze with ${activeProviderLabel}`}</button>{submitErrorNote}</form>}</>}
      </section>
      <section className="panel"><div className="panel-title-row"><div><p className="eyebrow">INGESTION HISTORY</p><h2>Submissions</h2><span className="muted-copy">Pending reviews: {pendingReviewCount}</span></div><Badge>{submissions.length}</Badge></div>{loading && !submissions.length ? <Loading label="Loading submissions" /> : submissions.length ? <div className="submission-list">{submissions.map((item) => <article className="submission-row" key={item.id}><div><strong>{item.source_title}</strong><span>{item.source_type} · {new Date(item.submitted_at).toLocaleString()}</span></div><div className="submission-actions"><Badge tone={item.status === "failed" ? "rose" : item.status === "draft_ready" ? "mint" : "blue"}>{item.status}</Badge><Badge tone={item.review_status === "published" ? "mint" : item.review_status === "rejected" ? "rose" : "violet"}>Review: {item.review_status}</Badge><button type="button" className="button button-danger" disabled={saving} aria-label={`Delete submission ${item.source_title}`} onClick={() => { setNotice(null); setSubmissionToDelete(item); }}>Delete</button></div><small>{item.finding_count} findings · {item.draft_count} drafts</small></article>)}</div> : <EmptyState title="No research submitted" message="Your analyzed sources will appear here." />}</section>
    </div>
    <section className="panel research-drafts"><div className="panel-title-row"><div><p className="eyebrow">REVIEW QUEUE</p><h2>Draft expectations</h2></div><Badge>{drafts.filter((draft) => draft.status === "draft").length} awaiting review</Badge></div>{drafts.length ? <div className="draft-list">{drafts.map((draft) => <article className="draft-card" key={draft.id}><div className="draft-heading"><div><Badge tone="violet">{draft.domain_name}</Badge><Badge>{draft.career_level_name}</Badge><h3>{draft.competency_name}</h3></div><Badge tone={draft.status === "published" ? "mint" : draft.status === "rejected" ? "rose" : "amber"}>{draft.status}</Badge></div><label>Expectation<textarea rows="3" value={editValue(draft, "expectation_description")} disabled={draft.status === "published"} onChange={(event) => setEdit(draft, "expectation_description", event.target.value)} /></label><div className="draft-fields"><label>Proficiency<input value={editValue(draft, "proficiency_level")} disabled={draft.status === "published"} onChange={(event) => setEdit(draft, "proficiency_level", event.target.value)} /></label><label>Importance<input value={editValue(draft, "importance")} disabled={draft.status === "published"} onChange={(event) => setEdit(draft, "importance", event.target.value)} /></label><label>Reviewer note<input value={editValue(draft, "reviewer_note") || ""} disabled={draft.status === "published"} onChange={(event) => setEdit(draft, "reviewer_note", event.target.value)} /></label></div><div className="evidence-list"><span className="source-label">Evidence excerpts</span>{draft.evidence.map((evidence) => <blockquote key={`${draft.id}-${evidence.supporting_excerpt}`}>“{evidence.supporting_excerpt}” <small>{evidence.source_title}</small></blockquote>)}</div><div className="draft-actions">{["draft", "rejected"].includes(draft.status) && <><button className="button button-secondary" disabled={saving} onClick={() => update(draft)}>Save edits</button><button className="button" disabled={saving} onClick={() => review(draft, "approve")}>Approve</button></>}{draft.status === "draft" && <button className="button button-danger" disabled={saving} onClick={() => review(draft, "reject")}>Reject</button>}{draft.status === "approved" && <><button className="button button-danger" disabled={saving} onClick={() => review(draft, "reject")}>Reject</button><button className="button" disabled={saving} onClick={() => review(draft, "publish")}>Publish to taxonomy</button></>}{draft.status === "published" && <span className="muted-copy">Published expectation ID {draft.published_expectation_id}</span>}</div></article>)}</div> : <EmptyState title="Review queue is empty" message="Submit research to generate taxonomy-aware draft expectations." />}</section>
    {submissionToDelete && <div className="review-modal-backdrop" role="presentation"><section className="panel review-modal" role="dialog" aria-modal="true" aria-labelledby="delete-submission-title"><p className="eyebrow">DELETE SUBMISSION</p><h2 id="delete-submission-title">Delete {submissionToDelete.source_title}?</h2><p className="muted-copy">Are you sure you want to delete this research submission? Its unpublished findings, draft expectations, and associated review data will also be deleted. This action cannot be undone.</p><div className="review-card-actions"><button type="button" className="button button-secondary" disabled={saving} onClick={() => setSubmissionToDelete(null)}>Cancel</button><button type="button" className="button button-danger" disabled={saving} onClick={removeSubmission}>{saving ? "Deleting…" : "Delete Submission"}</button></div></section></div>}
  </>;
}
