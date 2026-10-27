import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ResearchAdminPage from "../src/ResearchAdminPage";

const draft = {
  id: 7, submission_id: 3, domain_id: 1, domain_name: "Cloud Infrastructure Security", career_level_id: 3,
  career_level_name: "Senior", competency_id: 2, competency_name: "Kubernetes Security",
  expectation_description: "Secure workloads.", proficiency_level: "advanced", importance: "essential",
  responsibility_type: "lead", experience_years_min: 4, experience_years_max: null, status: "draft",
  reviewer_note: null, reviewed_by: null, reviewed_at: null, published_expectation_id: null,
  evidence: [{ source_title: "Role brief", source_url: "about:blank", collected_at: "2026-01-01T00:00:00Z", supporting_excerpt: "Secure workloads." }],
};

function response(body, ok = true, status = 200) { return Promise.resolve({ ok, status, json: () => Promise.resolve(body) }); }

beforeEach(() => {
  global.fetch = vi.fn((url, options = {}) => {
    const path = new URL(url).pathname;
    if (path.endsWith("/ollama")) return response({ status: "configured", model: "gpt-oss:20b", active_model: "gpt-oss:20b", mode: "fallback", available_models: ["gpt-oss:20b", "qwen2.5:7b"], evaluations: [] });
    if (path.endsWith("/ollama/models/refresh")) return response({ status: "configured", model: "gpt-oss:20b", active_model: "gpt-oss:20b", mode: "fallback", available_models: ["gpt-oss:20b", "qwen2.5:7b"], evaluations: [] });
    if (path.endsWith("/ollama/evaluate")) return response({ status: "configured", model: "qwen2.5:7b", active_model: "qwen2.5:7b", mode: "automatic", evaluation_version: "cybersec-job-extraction-v1", available_models: ["gpt-oss:20b", "qwen2.5:7b"], evaluations: [{ model_name: "qwen2.5:7b", evaluation_version: "cybersec-job-extraction-v1", extraction_accuracy: 1, classification_accuracy: .9, json_validity: 1, hallucination_rate: 0, average_processing_ms: 120, overall_score: .95, error_message: null, evaluated_at: "2026-01-15T00:00:00Z" }] });
    if (path.endsWith("/ollama/select")) return response({ status: "configured", model: "qwen2.5:7b", active_model: "qwen2.5:7b", mode: "manual", available_models: ["gpt-oss:20b", "qwen2.5:7b"], evaluations: [] });
    if (path.endsWith("/import-url")) return response({ source_url: "https://jobs.example.test/security", job_title: "Senior Security Engineer", job_description: "Secure product releases.", extraction_method: "json_ld", date_posted: "2026-01-15", status: "success" });
    if (path.endsWith("/submissions") && options.method === "POST") return response({ id: 4, status: "draft_ready" }, true, 201);
    if (path.endsWith("/submissions")) return response({ items: [], total: 0 });
    if (path.endsWith("/drafts/7/approve")) return response({ status: "approved", draft: { ...draft, status: "approved" } });
    if (path.endsWith("/drafts")) return response({ items: [draft], total: 1 });
    return response({});
  });
});
afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });

describe("Phase 5 research console", () => {
  it("requires a key, submits text, and renders evidence review", async () => {
    render(<ResearchAdminPage />);
    expect(screen.getByText("Unlock the research console")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Administrator API key"), { target: { value: "test-admin-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Open research console" }));
    await waitFor(() => expect(screen.getByText("Research consolidation")).toBeTruthy());
    expect(screen.getAllByText(/gpt-oss:20b/).length).toBeGreaterThan(0);
    expect(screen.getByText("Kubernetes Security")).toBeTruthy();
    expect(screen.getByText("Secure workloads.")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Job description"), { target: { value: "Senior Kubernetes security role" } });
    fireEvent.click(screen.getByRole("button", { name: "Analyze pasted text" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining("/research/submissions"), expect.objectContaining({ method: "POST" })));
  });

  it("previews a URL import, allows edits, and waits for explicit analysis", async () => {
    render(<ResearchAdminPage />);
    fireEvent.change(screen.getByLabelText("Administrator API key"), { target: { value: "test-admin-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Open research console" }));
    await waitFor(() => expect(screen.getByText("Research consolidation")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Import from URL" }));
    fireEvent.change(screen.getByLabelText("Job Posting URL"), { target: { value: "https://jobs.example.test/security" } });
    fireEvent.click(screen.getByRole("button", { name: "Fetch Job Description" }));
    await waitFor(() => expect(screen.getByDisplayValue("Senior Security Engineer")).toBeTruthy());
    expect(global.fetch.mock.calls.some(([requestUrl, options]) => requestUrl.endsWith("/research/submissions") && options?.method === "POST")).toBe(false);
    fireEvent.change(screen.getByLabelText("Editable job description"), { target: { value: "Corrected security responsibilities." } });
    fireEvent.click(screen.getByRole("button", { name: "Analyze with Ollama" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining("/research/submissions"), expect.objectContaining({ method: "POST", body: expect.stringContaining("url_imported") })));
  });

  it("sends a missing posted date as null and shows analysis errors next to the button", async () => {
    const baseFetch = global.fetch;
    global.fetch = vi.fn((url, options = {}) => {
      const path = new URL(url).pathname;
      if (path.endsWith("/import-url")) return response({ source_url: "https://jobs.example.test/security", job_title: "Senior Security Engineer", job_description: "Secure product releases.", extraction_method: "json_ld", date_posted: null, status: "success" });
      if (path.endsWith("/submissions") && options.method === "POST") return response({ detail: [{ loc: ["body", "content"], msg: "String should have at least 1 character" }] }, false, 422);
      return baseFetch(url, options);
    });
    render(<ResearchAdminPage />);
    fireEvent.change(screen.getByLabelText("Administrator API key"), { target: { value: "test-admin-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Open research console" }));
    await waitFor(() => expect(screen.getByText("Research consolidation")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Import from URL" }));
    fireEvent.change(screen.getByLabelText("Job Posting URL"), { target: { value: "https://jobs.example.test/security" } });
    fireEvent.click(screen.getByRole("button", { name: "Fetch Job Description" }));
    await waitFor(() => expect(screen.getByDisplayValue("Senior Security Engineer")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Analyze with/ }));
    await waitFor(() => expect(screen.getByText("Analysis failed: content: String should have at least 1 character")).toBeTruthy());
    const [, submitOptions] = global.fetch.mock.calls.find(([requestUrl, options]) => requestUrl.endsWith("/research/submissions") && options?.method === "POST");
    expect(JSON.parse(submitOptions.body).research_date).toBeNull();
  });

  it("keeps the form and explains provider failures such as a retired OpenWebUI model", async () => {
    const baseFetch = global.fetch;
    global.fetch = vi.fn((url, options = {}) => {
      const path = new URL(url).pathname;
      if (path.endsWith("/research/models")) return response({ active_provider: "openwebui", active_model_id: "retired-model", active_model_name: "retired-model", mode: "manual", evaluations: [], providers: [{ provider: "openwebui", status: "connected", models: [{ provider: "openwebui", id: "claude-sonnet-5-5", name: "Claude Sonnet" }], error: null }] });
      if (path.endsWith("/submissions") && options.method === "POST") return response({ id: 9, status: "failed", error_message: "Model 'retired-model' is no longer available in OpenWebUI; select another model" }, true, 201);
      return baseFetch(url, options);
    });
    render(<ResearchAdminPage />);
    fireEvent.change(screen.getByLabelText("Administrator API key"), { target: { value: "test-admin-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Open research console" }));
    await waitFor(() => expect(screen.getByText(/The active model "retired-model" is not offered by OpenWebUI/)).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Job description"), { target: { value: "Cloud security role" } });
    fireEvent.click(screen.getByRole("button", { name: "Analyze pasted text" }));
    await waitFor(() => expect(screen.getByText("Analysis failed: Model 'retired-model' is no longer available in OpenWebUI; select another model")).toBeTruthy());
    expect(screen.getByDisplayValue("Cloud security role")).toBeTruthy();
  });

  it("refreshes, evaluates, and manually selects an installed model", async () => {
    render(<ResearchAdminPage />);
    fireEvent.change(screen.getByLabelText("Administrator API key"), { target: { value: "test-admin-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Open research console" }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Installed Ollama model" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Evaluate Models" }));
    await waitFor(() => expect(screen.getAllByText("qwen2.5:7b").length).toBeGreaterThan(0));
    fireEvent.change(screen.getByRole("combobox", { name: "Installed Ollama model" }), { target: { value: "qwen2.5:7b" } });
    fireEvent.click(screen.getByRole("button", { name: "Use selected model" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining("/research/ollama/select"), expect.objectContaining({ method: "POST", body: JSON.stringify({ model_name: "qwen2.5:7b" }) })));
  });
});
