const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8100").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message, status = 0, detail = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const headers = isFormData ? { ...options.headers } : { "Content-Type": "application/json", ...options.headers };
  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  if (!response.ok) {
    let detail = null;
    try {
      detail = await response.json();
    } catch {
      detail = null;
    }
    throw new ApiError(detail?.detail || `Request failed with status ${response.status}`, response.status, detail);
  }
  return response.json();
}

function queryString(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  const result = search.toString();
  return result ? `?${result}` : "";
}

export function fetchHealth() { return request("/api/v1/health"); }
export function fetchProfiles() { return request("/api/v1/profiles"); }
export function createProfile(profile) { return request("/api/v1/profiles", { method: "POST", body: JSON.stringify(profile) }); }
export function fetchDomains() { return request("/api/v1/domains"); }
export function fetchDomain(id) { return request(`/api/v1/domains/${id}`); }
export function fetchLevels() { return request("/api/v1/levels"); }
export function fetchCategories() { return request("/api/v1/categories"); }
export function fetchCompetencies(params = {}) { return request(`/api/v1/competencies${queryString(params)}`); }
export function fetchCompetency(id) { return request(`/api/v1/competencies/${id}`); }
export function fetchExpectations(params = {}) { return request(`/api/v1/expectations${queryString(params)}`); }
export function fetchExpectation(id) { return request(`/api/v1/expectations/${id}`); }
export function fetchCareerMatrix() { return request("/api/v1/career-matrix"); }
export function fetchComparison(domain, levels) { return request(`/api/v1/compare${queryString({ domain, levels: levels.join(",") })}`); }
export function fetchSearch(params = {}) { return request(`/api/v1/search${queryString(params)}`); }
export function fetchResearchSources(params = {}) { return request(`/api/v1/research-sources${queryString(params)}`); }


function adminHeaders(adminKey) { return adminKey ? { "X-Admin-API-Key": adminKey } : {}; }
export function fetchOllamaStatus(adminKey) { return request("/api/v1/research/ollama", { headers: adminHeaders(adminKey) }); }
export function submitResearchText(payload, adminKey) { return request("/api/v1/research/submissions", { method: "POST", headers: adminHeaders(adminKey), body: JSON.stringify(payload) }); }
export function refreshOllamaModels(adminKey) { return request("/api/v1/research/ollama/models/refresh", { method: "POST", headers: adminHeaders(adminKey) }); }
export function evaluateOllamaModels(adminKey) { return request("/api/v1/research/ollama/evaluate", { method: "POST", headers: adminHeaders(adminKey) }); }
export function selectOllamaModel(modelName, adminKey) { return request("/api/v1/research/ollama/select", { method: "POST", headers: adminHeaders(adminKey), body: JSON.stringify({ model_name: modelName }) }); }


function normalizeLegacyModels(status) {
  return {
    providers: [{
      provider: "ollama",
      status: status.status === "configured" ? "connected" : status.status,
      error: status.detail || null,
      models: (status.available_models || []).map((id) => ({ provider: "ollama", id, name: id, possible_duplicate: false, duplicate_with: [] })),
    }],
    active_provider: "ollama",
    active_model_id: status.active_model || status.model || "",
    active_model_name: status.active_model || status.model || "",
    mode: status.mode || "fallback",
    evaluation_version: status.evaluation_version || null,
    evaluations: (status.evaluations || []).map((evaluation) => ({ ...evaluation, provider: "ollama", model_id: evaluation.model_name })),
  };
}

export async function fetchAIModels(adminKey) {
  const result = await request("/api/v1/research/models", { headers: adminHeaders(adminKey) });
  return Array.isArray(result.providers) ? result : normalizeLegacyModels(await fetchOllamaStatus(adminKey));
}

export async function refreshAIModels(adminKey) {
  const result = await request("/api/v1/research/models/refresh", { method: "POST", headers: adminHeaders(adminKey) });
  return Array.isArray(result.providers) ? result : normalizeLegacyModels(await refreshOllamaModels(adminKey));
}

export async function evaluateAIModels(adminKey) {
  const result = await request("/api/v1/research/models/evaluate", { method: "POST", headers: adminHeaders(adminKey) });
  return Array.isArray(result.providers) ? result : normalizeLegacyModels(await evaluateOllamaModels(adminKey));
}

export async function selectAIModel(provider, modelId, adminKey) {
  const result = await request("/api/v1/research/models/select", { method: "POST", headers: adminHeaders(adminKey), body: JSON.stringify({ provider, model_id: modelId }) });
  return Array.isArray(result.providers) ? result : normalizeLegacyModels(await selectOllamaModel(modelId, adminKey));
}

export async function testAIModel(provider, modelId, adminKey) {
  return request("/api/v1/research/models/test", { method: "POST", headers: adminHeaders(adminKey), body: JSON.stringify({ provider, model_id: modelId }) });
}

export function importResearchUrl(url, adminKey) { return request("/api/v1/research/import-url", { method: "POST", headers: adminHeaders(adminKey), body: JSON.stringify({ url }) }); }

export function submitResearchFile(formData, adminKey) { return request("/api/v1/research/submissions/file", { method: "POST", headers: adminHeaders(adminKey), body: formData }); }
export function fetchResearchSubmissions(adminKey) { return request("/api/v1/research/submissions", { headers: adminHeaders(adminKey) }); }
export function fetchResearchDrafts(status, adminKey) { return request(`/api/v1/research/drafts${queryString({ status_filter: status })}`, { headers: adminHeaders(adminKey) }); }
export function updateResearchDraft(id, payload, adminKey) { return request(`/api/v1/research/drafts/${id}`, { method: "PATCH", headers: adminHeaders(adminKey), body: JSON.stringify(payload) }); }
export function approveResearchDraft(id, reviewer_note, adminKey) { return request(`/api/v1/research/drafts/${id}/approve`, { method: "POST", headers: adminHeaders(adminKey), body: JSON.stringify({ reviewer_note }) }); }
export function rejectResearchDraft(id, reviewer_note, adminKey) { return request(`/api/v1/research/drafts/${id}/reject`, { method: "POST", headers: adminHeaders(adminKey), body: JSON.stringify({ reviewer_note }) }); }
export function publishResearchDraft(id, adminKey) { return request(`/api/v1/research/drafts/${id}/publish`, { method: "POST", headers: adminHeaders(adminKey) }); }

