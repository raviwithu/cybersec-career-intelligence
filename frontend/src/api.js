const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8100").replace(/\/$/, "");
const ADMIN_SESSION_KEY = "cybersec-career-intelligence.admin-api-key";

export function getAdminSessionKey() { return typeof window === "undefined" ? "" : window.sessionStorage.getItem(ADMIN_SESSION_KEY) || ""; }
export function setAdminSessionKey(value) { if (typeof window !== "undefined") window.sessionStorage.setItem(ADMIN_SESSION_KEY, value); }
export function clearAdminSessionKey() { if (typeof window !== "undefined") window.sessionStorage.removeItem(ADMIN_SESSION_KEY); }


export class ApiError extends Error {
  constructor(message, status = 0, detail = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function errorMessage(detail) {
  // FastAPI validation errors arrive as a list of { loc, msg } objects.
  if (Array.isArray(detail)) return detail.map((item) => `${(item.loc || []).filter((part) => part !== "body").join(".")}: ${item.msg}`).join("; ");
  return typeof detail === "string" ? detail : null;
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
    throw new ApiError(errorMessage(detail?.detail) || `Request failed with status ${response.status}`, response.status, detail);
  }
  if (response.status === 204) return null;
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
export function fetchIndustries() { return request("/api/v1/industries"); }
export function fetchCompetencies(params = {}) { return request(`/api/v1/competencies${queryString(params)}`); }
export function fetchCompetency(id, params = {}) { return request(`/api/v1/competencies/${id}${queryString(params)}`); }
export function fetchExpectations(params = {}) { return request(`/api/v1/expectations${queryString(params)}`); }
export function fetchExpectation(id, params = {}) { return request(`/api/v1/expectations/${id}${queryString(params)}`); }
export function fetchCareerMatrix(params = {}) { return request(`/api/v1/career-matrix${queryString(params)}`); }
export function fetchComparison(domain, levels, params = {}) { return request(`/api/v1/compare${queryString({ domain, levels: levels.join(","), ...params })}`); }
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
    evaluations: (status.evaluations || []).map((evaluation) => ({ ...evaluation, provider: "ollama", model_id: evaluation.model_name, domain_accuracy: evaluation.domain_accuracy ?? evaluation.classification_accuracy ?? 0, career_level_accuracy: evaluation.career_level_accuracy ?? evaluation.classification_accuracy ?? 0 })),
  };
}

async function unifiedOrLegacy(unifiedRequest, legacyRequest) {
  try {
    const result = await unifiedRequest();
    return Array.isArray(result.providers) ? result : normalizeLegacyModels(await legacyRequest());
  } catch (error) {
    if (error.status !== 404) throw error;
    return normalizeLegacyModels(await legacyRequest());
  }
}

export function fetchAIModels(adminKey) {
  return unifiedOrLegacy(
    () => request("/api/v1/research/models", { headers: adminHeaders(adminKey) }),
    () => fetchOllamaStatus(adminKey),
  );
}

export function refreshAIModels(adminKey) {
  return unifiedOrLegacy(
    () => request("/api/v1/research/models/refresh", { method: "POST", headers: adminHeaders(adminKey) }),
    () => refreshOllamaModels(adminKey),
  );
}

export function evaluateAIModels(adminKey) {
  return unifiedOrLegacy(
    () => request("/api/v1/research/models/evaluate", { method: "POST", headers: adminHeaders(adminKey) }),
    () => evaluateOllamaModels(adminKey),
  );
}

export function selectAIModel(provider, modelId, adminKey) {
  return unifiedOrLegacy(
    () => request("/api/v1/research/models/select", { method: "POST", headers: adminHeaders(adminKey), body: JSON.stringify({ provider, model_id: modelId }) }),
    () => selectOllamaModel(modelId, adminKey),
  );
}

export async function testAIModel(provider, modelId, adminKey) {
  return request("/api/v1/research/models/test", { method: "POST", headers: adminHeaders(adminKey), body: JSON.stringify({ provider, model_id: modelId }) });
}

export function importResearchUrl(url, adminKey) { return request("/api/v1/research/import-url", { method: "POST", headers: adminHeaders(adminKey), body: JSON.stringify({ url }) }); }

export function submitResearchFile(formData, adminKey) { return request("/api/v1/research/submissions/file", { method: "POST", headers: adminHeaders(adminKey), body: formData }); }
export function fetchResearchSubmissions(adminKey) { return request("/api/v1/research/submissions", { headers: adminHeaders(adminKey) }); }
export function deleteResearchSubmission(id, adminKey) { return request(`/api/v1/research/submissions/${id}`, { method: "DELETE", headers: adminHeaders(adminKey) }); }
export function fetchResearchDrafts(status, adminKey) { return request(`/api/v1/research/drafts${queryString({ status_filter: status })}`, { headers: adminHeaders(adminKey) }); }
export function updateResearchDraft(id, payload, adminKey) { return request(`/api/v1/research/drafts/${id}`, { method: "PATCH", headers: adminHeaders(adminKey), body: JSON.stringify(payload) }); }
export function approveResearchDraft(id, reviewer_note, adminKey) { return request(`/api/v1/research/drafts/${id}/approve`, { method: "POST", headers: adminHeaders(adminKey), body: JSON.stringify({ reviewer_note }) }); }
export function rejectResearchDraft(id, reviewer_note, adminKey) { return request(`/api/v1/research/drafts/${id}/reject`, { method: "POST", headers: adminHeaders(adminKey), body: JSON.stringify({ reviewer_note }) }); }
export function publishResearchDraft(id, adminKey) { return request(`/api/v1/research/drafts/${id}/publish`, { method: "POST", headers: adminHeaders(adminKey) }); }


export function fetchResearchReviewDashboard(params = {}, adminKey) { return request(`/api/v1/research/review/dashboard${queryString(params)}`, { headers: adminHeaders(adminKey) }); }
export function fetchResearchReviewSubmission(id, adminKey) { return request(`/api/v1/research/review/submissions/${id}`, { headers: adminHeaders(adminKey) }); }
export function fetchResearchReviewComparison(id, adminKey) { return request(`/api/v1/research/review/changes/${id}/comparison`, { headers: adminHeaders(adminKey) }); }
export function acceptResearchReviewChange(id, expected_version, reviewer_note, adminKey, publish = false) { return request(`/api/v1/research/review/changes/${id}/accept`, { method: "POST", headers: adminHeaders(adminKey), body: JSON.stringify({ expected_version, reviewer_note: reviewer_note || null, publish }) }); }
export function modifyResearchReviewChange(id, payload, adminKey) { return request(`/api/v1/research/review/changes/${id}`, { method: "PATCH", headers: adminHeaders(adminKey), body: JSON.stringify(payload) }); }
export function rejectResearchReviewChange(id, expected_version, reviewer_note, adminKey) { return request(`/api/v1/research/review/changes/${id}/reject`, { method: "POST", headers: adminHeaders(adminKey), body: JSON.stringify({ expected_version, reviewer_note: reviewer_note || null }) }); }
export function fetchResearchPublicationPreview(adminKey) { return request("/api/v1/research/review/publication-preview", { headers: adminHeaders(adminKey) }); }
export function publishResearchReview(payload, adminKey) { return request("/api/v1/research/review/publish", { method: "POST", headers: adminHeaders(adminKey), body: JSON.stringify(payload) }); }
export function fetchResearchReviewHistory(adminKey) { return request("/api/v1/research/review/history", { headers: adminHeaders(adminKey) }); }
