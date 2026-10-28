import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../src/App";

const health = { status: "healthy", services: { postgres: { status: "up" }, redis: { status: "up" }, ollama: { status: "up" } } };
const levels = [
  { id: 1, name: "Junior", slug: "junior", career_track: "shared", description: "", display_order: 1 },
  { id: 2, name: "Intermediate", slug: "intermediate", career_track: "shared", description: "", display_order: 2 },
  { id: 3, name: "Senior", slug: "senior", career_track: "technical", description: "", display_order: 3 },
  { id: 4, name: "Manager", slug: "manager", career_track: "management", description: "", display_order: 4 },
  { id: 5, name: "Architect", slug: "architect", career_track: "technical", description: "", display_order: 5 },
  { id: 6, name: "Director", slug: "director", career_track: "management", description: "", display_order: 6 },
];
const domain = { id: 1, name: "Embedded Systems Security", slug: "embedded-systems-security", description: "Protect embedded products.", parent_id: null, display_order: 1, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", children: [{ id: 2, name: "Boot Security", slug: "boot-security", description: "Trusted startup.", parent_id: 1, display_order: 1, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", children: [] }] };
const category = { id: 1, name: "Technical Knowledge", slug: "technical-knowledge", description: "Knowledge." };
const practicalCategory = { id: 2, name: "Security Architecture", slug: "security-architecture", description: "Architecture." };
const industries = [{ id: 1, name: "Automotive", slug: "automotive", aliases: [] }];
const evidenceSource = { id: 8, source_type: "standard", source_url: "https://source.test/secure-boot", source_title: "Secure Boot Standard", collected_at: "2026-01-15T00:00:00Z", notes: null, expectation_ids: [1] };
const competency = { id: 1, name: "Secure Boot", slug: "secure-boot", description: "Design a trusted boot chain.", category, domains: [{ id: 2, name: "Boot Security", slug: "boot-security" }], career_levels: [levels[2], levels[4]] };
const secondCompetency = { id: 2, name: "Threat Modeling", slug: "threat-modeling", description: "Identify trust boundaries.", category: practicalCategory, domains: [{ id: 2, name: "Boot Security", slug: "boot-security" }], career_levels: [levels[2]] };
const expectation = { id: 1, domain: { id: 2, name: "Boot Security", slug: "boot-security" }, career_level: levels[4], competency, expectation_description: "Design and validate a trusted boot chain.", technical_knowledge: "Trust anchors and verified startup.", practical_capability: "Evaluate firmware tampering resistance.", tools_technologies: "TPM", qualifications: "", proficiency_level: "expert", importance: "essential", responsibility_type: "design", experience_years_min: 7, experience_years_max: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", supporting_sources: [{ source: evidenceSource, supporting_excerpt: "Verified startup protects firmware integrity." }] };
const secondExpectation = { id: 2, domain: expectation.domain, career_level: levels[2], competency: secondCompetency, expectation_description: "Model threats across system trust boundaries.", technical_knowledge: "Threat modeling methods.", practical_capability: "Document prioritized mitigations.", tools_technologies: "", qualifications: "", proficiency_level: "advanced", importance: "important", responsibility_type: "leadership", experience_years_min: null, experience_years_max: null, created_at: expectation.created_at, updated_at: expectation.updated_at, supporting_sources: [] };
const matrix = { levels, domains: [{ domain: { id: 2, name: "Boot Security", slug: "boot-security" }, cells: levels.map((level) => ({ domain_id: 2, career_level_id: level.id, expectation_count: level.slug === "architect" ? 1 : 0, competency_count: level.slug === "architect" ? 1 : 0, category_distribution: { "technical-knowledge": 1 } })) }] };
const page = (items, total = items.length) => ({ items, meta: { page: 1, page_size: 100, total, pages: total ? 1 : 0 } });

function response(body, ok = true, status = 200) { return Promise.resolve({ ok, status, json: () => Promise.resolve(body) }); }
function mockApi({ fail = false, empty = false } = {}) {
  return vi.fn((url) => {
    if (fail) return response({ detail: "API unavailable" }, false, 503);
    const path = new URL(url).pathname;
    if (path.endsWith("/health")) return response(health);
    if (path.endsWith("/domains")) return response([domain]);
    if (path.endsWith("/levels")) return response(levels);
    if (path.endsWith("/categories")) return response([category, practicalCategory]);
    if (path.endsWith("/industries")) return response(industries);
    if (path.endsWith("/career-matrix")) return response(matrix);
    if (path.endsWith("/competencies/1")) return response({ ...competency, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", related_competencies: [], expectations: [{ ...expectation, domain: expectation.domain, career_level: expectation.career_level }] });
    if (path.endsWith("/competencies")) return response(page(empty ? [] : [competency], empty ? 0 : 1));
    if (path.endsWith("/expectations")) return response(page(empty ? [] : [expectation, secondExpectation], empty ? 0 : 2));
    if (path.endsWith("/compare")) return response({ domain: { id: 2, name: "Boot Security", slug: "boot-security" }, levels: [{ level: levels[2], competency_ids: [1], competency_count: 1 }, { level: levels[4], competency_ids: [1], competency_count: 1 }], shared_competencies: [{ competency, expectations_by_level: { senior: [expectation], architect: [expectation] }, proficiency_by_level: { senior: ["advanced"], architect: ["expert"] }, responsibilities_by_level: { senior: ["implement"], architect: ["design"] } }], unique_competencies: { senior: [], architect: [] }, differences: [] });
    if (path.endsWith("/search")) return response(page(empty ? [] : [{ result_type: "competency", id: 1, name: "Secure Boot", description: competency.description, competency_id: 1 }], empty ? 0 : 1));
    if (path.endsWith("/intelligence/evidence")) return response({ competency: { id: 1, name: "Secure Boot", slug: "secure-boot" }, total: 1, data_quality: [], evidence: [{ expectation_id: 1, source_id: 8, source_title: evidenceSource.source_title, source_url: evidenceSource.source_url, research_date: evidenceSource.collected_at, excerpt: "Verified startup protects firmware integrity.", publication_version: 3 }] });
    if (path.endsWith("/profiles")) return response([]);
    if (path.endsWith("/research/models")) return response({ providers: [{ provider: "ollama", status: "connected", models: [{ id: "model:test", name: "model:test" }] }], active_provider: "ollama", active_model_id: "model:test", active_model_name: "model:test", mode: "manual", evaluations: [] });
    if (path.endsWith("/research/submissions")) return response({ items: [], total: 0 });
    if (path.endsWith("/research/drafts")) return response({ items: [], total: 0 });
    if (path.endsWith("/research/review/dashboard")) return response({ pending_reviews: [], approved_changes: [], rejected_findings: [], change_history: [], filters: { domains: [], career_levels: [], categories: [], sources: [] } });
    if (path.endsWith("/job-searches/provider-status")) return response([{ provider_type: "linkedin_authorized", status: "unconfigured", display_name: "Authorized LinkedIn integration", limitations: ["Requires authorized access"], configured: false }, { provider_type: "import", status: "configured", display_name: "Permitted import", limitations: ["Uses permitted URLs or datasets"], configured: true }]);
    if (path.endsWith("/job-searches")) return response([]);
    return response({});
  });
}

beforeEach(() => { sessionStorage.clear(); window.location.hash = ""; global.fetch = mockApi(); });
afterEach(() => { sessionStorage.clear(); window.location.hash = ""; vi.restoreAllMocks(); });

describe("Phase 4 knowledge workspace", () => {
  it("renders dashboard statistics from backend data", async () => {
    render(<App />);
    expect(await screen.findByText("Cybersecurity career intelligence")).toBeTruthy();
    expect(screen.getByText("Embedded subdomains")).toBeTruthy();
    expect(screen.getByText("1/6")).toBeTruthy();
  });

  it("opens Career Readiness with compact context filters and category navigation", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Career Development" }));
    fireEvent.click(await screen.findByRole("button", { name: /Career Readiness/ }));
    expect(await screen.findByRole("heading", { name: /Career Readiness/ })).toBeTruthy();
    expect(screen.getByRole("combobox", { name: "Security Domain" }).value).toBe("embedded-systems-security");
    fireEvent.change(screen.getByRole("combobox", { name: "Security Subdomain" }), { target: { value: "boot-security" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Industry" }), { target: { value: "automotive" } });
    expect(screen.getByRole("combobox", { name: "Security Subdomain" }).value).toBe("boot-security");
    expect(screen.getByRole("combobox", { name: "Industry" }).value).toBe("automotive");
    fireEvent.click(await screen.findByRole("tab", { name: /Security Architecture/ }));
    const competencyCards = within(document.querySelector(".readiness-card-list"));
    expect(competencyCards.getByRole("heading", { name: "Threat Modeling" })).toBeTruthy();
    expect(competencyCards.queryByRole("heading", { name: "Secure Boot" })).toBeNull();
  });

  it("searches and expands one competency card with accessible evidence drawer", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Career Development" }));
    fireEvent.click(await screen.findByRole("button", { name: /Career Readiness/ }));
    const search = await screen.findByRole("textbox", { name: "Search within competencies" });
    fireEvent.change(search, { target: { value: "secure boot" } });
    expect(screen.queryByText("Threat Modeling")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    expect(screen.getByText("What you need to know")).toBeTruthy();
    const evidenceButton = screen.getByRole("button", { name: /View supporting evidence/ });
    fireEvent.click(evidenceButton);
    expect(await screen.findByRole("dialog", { name: "Secure Boot" })).toBeTruthy();
    expect(await screen.findByText("Secure Boot Standard")).toBeTruthy();
    expect(screen.getByText("Publication version")).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Secure Boot" })).toBeNull());
    expect(document.activeElement).toBe(evidenceButton);
  });

  it("keeps preparation actions separate and navigates to self-assessment and comparison", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Career Development" }));
    fireEvent.click(await screen.findByRole("button", { name: /Career Readiness/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Self-assess skills/ }));
    expect(await screen.findByRole("heading", { name: "Competency Gap Analysis" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Career Readiness/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Compare career levels/ }));
    expect(await screen.findByText("Make progression visible")).toBeTruthy();
  });

  it("shows the readiness empty state when filters return no expectations", async () => {
    global.fetch = mockApi({ empty: true });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Career Development" }));
    fireEvent.click(await screen.findByRole("button", { name: /Career Readiness/ }));
    expect(await screen.findByText("No competencies match these filters")).toBeTruthy();
  });

  it("refreshes domains when navigating so newly published research appears without a reload", async () => {
    render(<App />);
    expect(await screen.findByText("Cybersecurity career intelligence")).toBeTruthy();
    const grc = { ...domain, id: 11, name: "Governance, Risk, and Compliance", slug: "governance-risk-compliance", display_order: 6, children: [] };
    const baseFetch = global.fetch;
    global.fetch = vi.fn((url, options) => new URL(url).pathname.endsWith("/domains") ? response([domain, grc]) : baseFetch(url, options));
    fireEvent.click(screen.getByRole("button", { name: "Explore" }));
    fireEvent.click(screen.getByText("Domain Explorer"));
    expect(await screen.findByText("Governance, Risk, and Compliance")).toBeTruthy();
  });

  it("navigates domains, selects a subdomain and career level", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Explore" }));
    fireEvent.click(await screen.findByText("Domain Explorer"));
    expect(await screen.findByText("Select a security domain")).toBeTruthy();
    fireEvent.click(screen.getByText("Boot Security"));
    expect(await screen.findByText("Understand the work by domain")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Architect" }));
    expect(await screen.findByText("Design and validate a trusted boot chain.")).toBeTruthy();
  });

  it("opens a matrix cell into the matching expectations", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Explore" }));
    fireEvent.click(await screen.findByText("Career Matrix"));
    fireEvent.click(screen.getByRole("button", { name: /Boot Security, Architect: 1 expectations/ }));
    expect(await screen.findByText("Design and validate a trusted boot chain.")).toBeTruthy();
  });

  it("runs a career comparison using selected levels", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Explore" }));
    fireEvent.click(await screen.findByText("Career Comparison"));
    expect(await screen.findByText("Make progression visible")).toBeTruthy();
    expect(await screen.findByText("Shared competencies")).toBeTruthy();
    expect(screen.getByText("Secure Boot")).toBeTruthy();
  });

  it("searches competencies and opens competency detail", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Explore" }));
    fireEvent.click(await screen.findByRole("button", { name: /Competency Explorer/ }));
    expect(await screen.findByText("Browse the building blocks")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Secure Boot/ }));
    expect(await screen.findByText("RELATED COMPETENCIES")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Search the knowledge base/ }));
    fireEvent.change(screen.getByLabelText("Global search"), { target: { value: "secure" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit search" }));
    expect(await screen.findByText("1 results for")).toBeTruthy();
  });

  it("preserves direct access to the legacy automated research route", async () => {
    window.location.hash = "#automated-research";
    render(<App />);
    expect(await screen.findByText("Unlock automated research")).toBeTruthy();
    expect(screen.queryByText("Administration")).toBeNull();
  });

  it("renders the LinkedIn Job Search workspace with provider status", async () => {
    sessionStorage.setItem("cybersec-career-intelligence.admin-api-key", "test-admin-key");
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Administration" }));
    fireEvent.click(await screen.findByRole("button", { name: "Research Ingestion" }));
    fireEvent.click(await screen.findByRole("tab", { name: /Saved Searches/ }));
    expect(await screen.findByText("Authorized search results integration")).toBeTruthy();
    expect(screen.getByText("No undocumented APIs")).toBeTruthy();
  });


  it("shows empty states and API errors", async () => {
    global.fetch = mockApi({ empty: true });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Explore" }));
    fireEvent.click(await screen.findByText("Domain Explorer"));
    fireEvent.click(screen.getByText("Boot Security"));
    expect(await screen.findByText("No expectations in this view")).toBeTruthy();

    global.fetch = mockApi({ fail: true });
    render(<App />);
    expect(await screen.findByText("Unable to load this view")).toBeTruthy();
  });

  it("supports the mobile navigation control", async () => {
    render(<App />);
    const menu = await screen.findByRole("button", { name: "Open navigation" });
    fireEvent.click(menu);
    expect(screen.getByRole("button", { name: "Close navigation" })).toBeTruthy();
  });

  it("applies the selected industry to shared read requests", async () => {
    render(<App />);
    const scope = await screen.findByRole("combobox", { name: "Industry scope" });
    fireEvent.change(scope, { target: { value: "automotive" } });
    await waitFor(() => expect(global.fetch.mock.calls.some(([url]) => url.includes("/career-matrix?industry=automotive"))).toBe(true));
    expect(scope.value).toBe("automotive");
  });
});
