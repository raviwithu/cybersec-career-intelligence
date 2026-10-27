import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ResearchReviewPage from "../src/ResearchReviewPage";

const change = { id: 41, finding_id: 77, submission_id: 12, change_type: "new_competency", status: "pending", version: 1, proposed: { competency_name: "Firmware Integrity", expectation_description: "Design firmware integrity controls.", practical_capability: "Design firmware integrity controls.", evidence: [{ source_id: 9, excerpt: "Firmware integrity controls." }] } };
const finding = { id: 77, finding_type: "security-architecture", candidate_name: "Firmware Integrity", normalized_name: "firmware-integrity", technical_knowledge: "Firmware trust anchors", practical_capability: "Design firmware integrity controls.", qualifications: "", tools_technologies: "TPM", responsibilities: "Lead reviews.", proficiency_level: "advanced", importance: "essential", experience_years_min: null, experience_years_max: null, evidence_excerpt: "Firmware integrity controls.", confidence: null, confidence_meaningful: false, status: "extracted", classification_gaps: [], domains: [{ id: 3, name: "Embedded Systems Security", slug: "embedded-systems-security" }], career_level: { id: 5, name: "Architect", slug: "architect" }, category: { id: 1, name: "Security Architecture", slug: "security-architecture" }, competency: null, existing_matches: [], review_change: change };
const detail = { submission: { id: 12, source_id: 9, source_title: "Firmware role brief", source_url: "https://source.test/firmware", source_type: "pasted_text", submitted_at: "2026-01-15T00:00:00Z", completed_at: "2026-01-15T00:01:00Z", model_provider: "ollama", model_id: "model:test", model_name: "model:test", evaluation_version: "v1", status: "draft_ready", finding_count: 1, proposed_new_competencies: 1, proposed_updates: 0, potential_duplicates: 0, manual_classification_count: 0, review_status: "in_review" }, source: { id: 9, title: "Firmware role brief", url: "https://source.test/firmware", type: "pasted_text", provider: "ollama", model_name: "model:test" }, findings: [finding], domain_impact: [{ domain: { id: 3, name: "Embedded Systems Security" }, change_count: 1, career_levels: ["Architect"], new_competencies: ["Firmware Integrity"], modified_competencies: [], evidence_changes: 1 }] };
const dashboard = { pending_reviews: [detail.submission], approved_changes: [], rejected_findings: [], change_history: [], filters: { domains: [{ id: 3, name: "Embedded Systems Security", slug: "embedded-systems-security", parent_id: null }], career_levels: [{ id: 5, name: "Architect", slug: "architect" }], categories: [{ id: 1, name: "Security Architecture", slug: "security-architecture" }], sources: [{ id: 9, name: "Firmware role brief" }] } };

function response(body, ok = true, status = 200) { return Promise.resolve({ ok, status, json: () => Promise.resolve(body) }); }

beforeEach(() => {
  global.fetch = vi.fn((url, options = {}) => {
    const path = new URL(url).pathname;
    if (path.endsWith("/review/dashboard")) return response(dashboard);
    if (path.endsWith("/review/submissions/12")) return response(detail);
    if (path.endsWith("/review/publication-preview")) return response({ new_competencies: 1, updated_expectations: 0, merged_findings: 0, rejected_findings: 0, affected_domains: [{ id: 3, name: "Embedded Systems Security", change_count: 1 }], affected_career_levels: [{ id: 5, name: "Architect" }], changes: [{ ...change, status: "accepted", version: 2 }], ready: true, blockers: [] });
    if (path.endsWith("/review/changes/41/accept")) return response({ status: "accepted", change: { ...change, status: "accepted", version: 2 } });
    if (path.endsWith("/review/publish")) return response({ status: "published", batch_id: 4, published_change_ids: [41], published_expectation_ids: [88], published_competency_ids: [90] });
    return response({});
  });
});
afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });

describe("Research Review", () => {
  it("requires administrator access and renders evidence-first review details", async () => {
    render(<ResearchReviewPage />);
    expect(screen.getByText("Unlock research review")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Administrator API key"), { target: { value: "test-admin-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Open review workspace" }));
    await waitFor(() => expect(screen.getByText("Firmware role brief")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Firmware role brief/ }));
    await waitFor(() => expect(screen.getByText("Firmware Integrity")).toBeTruthy());
    expect(screen.getByText("Not provided")).toBeTruthy();
    expect(screen.getByText(/Firmware integrity controls/)).toBeTruthy();
    expect(screen.getAllByText("Embedded Systems Security").length).toBeGreaterThan(0);
  });

  it("accepts a finding and requires an explicit atomic publication confirmation", async () => {
    render(<ResearchReviewPage />);
    fireEvent.change(screen.getByLabelText("Administrator API key"), { target: { value: "test-admin-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Open review workspace" }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Firmware role brief/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Firmware role brief/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Accept" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(global.fetch.mock.calls.some(([url, options]) => url.endsWith("/review/changes/41/accept") && options.method === "POST")).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Review publication batch" }));
    await waitFor(() => expect(screen.getByText("Confirm knowledge-base changes")).toBeTruthy());
    expect(screen.getByText(/This batch publishes all approved changes together/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Publish approved batch" }));
    await waitFor(() => expect(global.fetch.mock.calls.some(([url, options]) => url.endsWith("/review/publish") && options.method === "POST")).toBe(true));
  });

  it("opens the edit form and saves a reviewed proposal", async () => {
    render(<ResearchReviewPage />);
    fireEvent.change(screen.getByLabelText("Administrator API key"), { target: { value: "test-admin-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Open review workspace" }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Firmware role brief/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Firmware role brief/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Edit decision" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Edit decision" }));
    expect(screen.getByText("Review structured knowledge")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save reviewed proposal" }));
    await waitFor(() => expect(global.fetch.mock.calls.some(([url, options]) => url.endsWith("/review/changes/41") && options.method === "PATCH")).toBe(true));
  });

  it("reuses the administrator key within the browser session", async () => {
    sessionStorage.setItem("cybersec-career-intelligence.admin-api-key", "test-admin-key");
    render(<ResearchReviewPage />);
    await waitFor(() => expect(screen.getByText("Firmware role brief")).toBeTruthy());
    expect(screen.queryByText("Unlock research review")).toBeNull();
  });
});
