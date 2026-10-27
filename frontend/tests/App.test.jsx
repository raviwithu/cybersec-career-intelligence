import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
const industries = [{ id: 1, name: "Automotive", slug: "automotive", aliases: [] }];
const competency = { id: 1, name: "Secure Boot", slug: "secure-boot", description: "Design a trusted boot chain.", category, domains: [{ id: 2, name: "Boot Security", slug: "boot-security" }], career_levels: [levels[2], levels[4]] };
const expectation = { id: 1, domain: { id: 2, name: "Boot Security", slug: "boot-security" }, career_level: levels[4], competency, expectation_description: "Design and validate a trusted boot chain.", proficiency_level: "expert", importance: "essential", responsibility_type: "design", experience_years_min: 7, experience_years_max: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", supporting_sources: [] };
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
    if (path.endsWith("/categories")) return response([category]);
    if (path.endsWith("/industries")) return response(industries);
    if (path.endsWith("/career-matrix")) return response(matrix);
    if (path.endsWith("/competencies/1")) return response({ ...competency, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", related_competencies: [], expectations: [{ ...expectation, domain: expectation.domain, career_level: expectation.career_level }] });
    if (path.endsWith("/competencies")) return response(page(empty ? [] : [competency], empty ? 0 : 1));
    if (path.endsWith("/expectations")) return response(page(empty ? [] : [expectation], empty ? 0 : 1));
    if (path.endsWith("/compare")) return response({ domain: { id: 2, name: "Boot Security", slug: "boot-security" }, levels: [{ level: levels[2], competency_ids: [1], competency_count: 1 }, { level: levels[4], competency_ids: [1], competency_count: 1 }], shared_competencies: [{ competency, expectations_by_level: { senior: [expectation], architect: [expectation] }, proficiency_by_level: { senior: ["advanced"], architect: ["expert"] }, responsibilities_by_level: { senior: ["implement"], architect: ["design"] } }], unique_competencies: { senior: [], architect: [] }, differences: [] });
    if (path.endsWith("/search")) return response(page(empty ? [] : [{ result_type: "competency", id: 1, name: "Secure Boot", description: competency.description, competency_id: 1 }], empty ? 0 : 1));
    if (path.endsWith("/profiles")) return response([]);
    if (path.endsWith("/job-searches/provider-status")) return response([{ provider_type: "linkedin_authorized", status: "unconfigured", display_name: "Authorized LinkedIn integration", limitations: ["Requires authorized access"], configured: false }, { provider_type: "import", status: "configured", display_name: "Permitted import", limitations: ["Uses permitted URLs or datasets"], configured: true }]);
    if (path.endsWith("/job-searches")) return response([]);
    return response({});
  });
}

beforeEach(() => { global.fetch = mockApi(); });
afterEach(() => vi.restoreAllMocks());

describe("Phase 4 knowledge workspace", () => {
  it("renders dashboard statistics from backend data", async () => {
    render(<App />);
    expect(await screen.findByText("Cybersecurity career intelligence")).toBeTruthy();
    expect(screen.getByText("Embedded subdomains")).toBeTruthy();
    expect(screen.getByText("1/6")).toBeTruthy();
  });

  it("refreshes domains when navigating so newly published research appears without a reload", async () => {
    render(<App />);
    expect(await screen.findByText("Cybersecurity career intelligence")).toBeTruthy();
    const grc = { ...domain, id: 11, name: "Governance, Risk, and Compliance", slug: "governance-risk-compliance", display_order: 6, children: [] };
    const baseFetch = global.fetch;
    global.fetch = vi.fn((url, options) => new URL(url).pathname.endsWith("/domains") ? response([domain, grc]) : baseFetch(url, options));
    fireEvent.click(screen.getByText("Domain Explorer"));
    expect(await screen.findByText("Governance, Risk, and Compliance")).toBeTruthy();
  });

  it("navigates domains, selects a subdomain and career level", async () => {
    render(<App />);
    fireEvent.click(await screen.findByText("Domain Explorer"));
    expect(await screen.findByText("Select a security domain")).toBeTruthy();
    fireEvent.click(screen.getByText("Boot Security"));
    expect(await screen.findByText("Understand the work by domain")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Architect" }));
    expect(await screen.findByText("Design and validate a trusted boot chain.")).toBeTruthy();
  });

  it("opens a matrix cell into the matching expectations", async () => {
    render(<App />);
    fireEvent.click(await screen.findByText("Career Matrix"));
    fireEvent.click(screen.getByRole("button", { name: /Boot Security, Architect: 1 expectations/ }));
    expect(await screen.findByText("Design and validate a trusted boot chain.")).toBeTruthy();
  });

  it("runs a career comparison using selected levels", async () => {
    render(<App />);
    fireEvent.click(await screen.findByText("Compare levels"));
    expect(await screen.findByText("Make progression visible")).toBeTruthy();
    expect(await screen.findByText("Shared competencies")).toBeTruthy();
    expect(screen.getByText("Secure Boot")).toBeTruthy();
  });

  it("searches competencies and opens competency detail", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Competencies$/ }));
    expect(await screen.findByText("Browse the building blocks")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Secure Boot/ }));
    expect(await screen.findByText("RELATED COMPETENCIES")).toBeTruthy();
    fireEvent.click(screen.getByText("Global search"));
    fireEvent.change(screen.getByLabelText("Global search"), { target: { value: "secure" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit search" }));
    expect(await screen.findByText("1 results for")).toBeTruthy();
  });

  it("opens the authenticated automated research workspace", async () => {
    sessionStorage.clear();
    render(<App />);
    fireEvent.click(await screen.findByText("Automated Research"));
    expect(await screen.findByText("Unlock automated research")).toBeTruthy();
  });

  it("renders the LinkedIn Job Search workspace with provider status", async () => {
    sessionStorage.setItem("cybersec-career-intelligence.admin-api-key", "test-admin-key");
    render(<App />);
    fireEvent.click(await screen.findByText("Automated Research"));
    fireEvent.click(await screen.findByText("LinkedIn Job Search"));
    expect(await screen.findByText("Authorized search results integration")).toBeTruthy();
    expect(screen.getByText("No undocumented APIs")).toBeTruthy();
  });


  it("shows empty states and API errors", async () => {
    global.fetch = mockApi({ empty: true });
    render(<App />);
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
