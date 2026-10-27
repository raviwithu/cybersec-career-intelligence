import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  acceptResearchReviewChange,
  clearAdminSessionKey,
  createProfile,
  deleteResearchSubmission,
  fetchAIModels,
  fetchCareerMatrix,
  fetchCompetencies,
  fetchExpectations,
  fetchSearch,
  setAdminSessionKey,
  submitResearchFile,
  submitResearchText,
} from "../src/api";

function response(body, ok = true, status = 200) {
  return Promise.resolve({ ok, status, json: () => Promise.resolve(body) });
}

describe("API client contracts", () => {
  beforeEach(() => {
    global.fetch = vi.fn(() => response({ ok: true }));
    sessionStorage.clear();
  });

  afterEach(() => vi.restoreAllMocks());

  it("builds read filters while omitting empty values", async () => {
    await fetchCompetencies({ domain: "boot-security", industry: "automotive", level: "" });
    expect(global.fetch).toHaveBeenLastCalledWith(
      "http://localhost:8100/api/v1/competencies?domain=boot-security&industry=automotive",
      expect.objectContaining({ headers: { "Content-Type": "application/json" } }),
    );

    await fetchExpectations({ industry: "medical-devices-healthcare-technology", page: 2 });
    await fetchCareerMatrix({ industry: "automotive" });
    await fetchSearch({ keyword: "secure boot", context: "vehicle platform" });
    expect(global.fetch.mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8100/api/v1/competencies?domain=boot-security&industry=automotive",
      "http://localhost:8100/api/v1/expectations?industry=medical-devices-healthcare-technology&page=2",
      "http://localhost:8100/api/v1/career-matrix?industry=automotive",
      "http://localhost:8100/api/v1/search?keyword=secure+boot&context=vehicle+platform",
    ]);
  });

  it("sends JSON payloads and administrator credentials for mutations", async () => {
    await createProfile({ full_name: "Ravi", target_role: "Security Engineer", skills: ["Python"] });
    await submitResearchText({ content: "Secure the release pipeline." }, "test-admin-key");
    await acceptResearchReviewChange(41, 3, "Reviewed", "test-admin-key", true);

    expect(global.fetch.mock.calls[0]).toEqual([
      "http://localhost:8100/api/v1/profiles",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ full_name: "Ravi", target_role: "Security Engineer", skills: ["Python"] }) }),
    ]);
    expect(global.fetch.mock.calls[1][1].headers).toEqual({ "Content-Type": "application/json", "X-Admin-API-Key": "test-admin-key" });
    expect(JSON.parse(global.fetch.mock.calls[2][1].body)).toEqual({ expected_version: 3, reviewer_note: "Reviewed", publish: true });
  });

  it("keeps multipart uploads free of an overridden content type", async () => {
    const form = new FormData();
    form.append("file", new Blob(["research"], { type: "text/plain" }), "research.txt");
    await submitResearchFile(form, "test-admin-key");
    expect(global.fetch).toHaveBeenCalledWith(
      "http://localhost:8100/api/v1/research/submissions/file",
      expect.objectContaining({ method: "POST", body: form, headers: { "X-Admin-API-Key": "test-admin-key" } }),
    );
  });

  it("normalizes legacy model responses after a unified endpoint is unavailable", async () => {
    global.fetch = vi.fn((url) => url.endsWith("/research/models")
      ? response({ detail: "not found" }, false, 404)
      : response({ status: "configured", model: "llama3.2", available_models: ["llama3.2"], evaluations: [] }));
    const models = await fetchAIModels("test-admin-key");
    expect(models.active_model_id).toBe("llama3.2");
    expect(models.providers[0].models[0]).toMatchObject({ provider: "ollama", id: "llama3.2" });
  });

  it("handles a successful 204 submission deletion without parsing JSON", async () => {
    global.fetch = vi.fn(() => response(null, true, 204));
    await expect(deleteResearchSubmission(9, "test-admin-key")).resolves.toBeNull();
    expect(global.fetch).toHaveBeenCalledWith(
      "http://localhost:8100/api/v1/research/submissions/9",
      expect.objectContaining({ method: "DELETE", headers: { "Content-Type": "application/json", "X-Admin-API-Key": "test-admin-key" } }),
    );
  });

  it("persists and clears the administrator session key and exposes API errors", async () => {
    setAdminSessionKey("test-admin-key");
    expect(sessionStorage.getItem("cybersec-career-intelligence.admin-api-key")).toBe("test-admin-key");
    clearAdminSessionKey();
    expect(sessionStorage.getItem("cybersec-career-intelligence.admin-api-key")).toBeNull();

    global.fetch = vi.fn(() => response({ detail: "Not authorized" }, false, 401));
    await expect(fetchSearch({ keyword: "secure" })).rejects.toEqual(expect.objectContaining({ name: "ApiError", status: 401, detail: { detail: "Not authorized" } }));
    await expect(fetchSearch({ keyword: "secure" })).rejects.toBeInstanceOf(ApiError);
  });
});
