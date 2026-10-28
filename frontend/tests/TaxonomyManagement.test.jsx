import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TaxonomyManagementPage from "../src/TaxonomyManagementPage";

const domain = {
  id: 101,
  taxonomy_type: "domain",
  name: "Embedded Systems Security",
  slug: "embedded-systems-security",
  description: "Embedded platforms.",
  parent_id: null,
  parent_name: null,
  career_track: null,
  display_order: 5,
  is_active: true,
  aliases: [{ alias: "Embedded Platform Security", requires_context: false, context_hint: null }],
  children: [],
  dependencies: { children: 0, published_expectations: 0, research_findings: 0, research_domain_links: 0, draft_expectations: 0 },
  updated_at: "2026-01-15T12:30:00Z",
};

function response(body, ok = true, status = 200) { return Promise.resolve({ ok, status, json: () => Promise.resolve(body) }); }

beforeEach(() => {
  global.fetch = vi.fn((url, options = {}) => {
    const path = new URL(url).pathname;
    if (path.endsWith("/taxonomy/history")) return response({ items: [], total: 0 });
    if (path.endsWith("/taxonomy") && !options.method) return response({ items: [domain], taxonomy_type: null });
    if (path.endsWith("/taxonomy/domain") && options.method === "POST") return response({ ...domain, id: 102, name: "Security Automation", slug: "security-automation" }, true, 201);
    if (path.endsWith("/taxonomy/domain/101/deactivate")) return response({ ...domain, is_active: false });
    if (path.endsWith("/taxonomy/domain/101/impact")) return response({ entry: domain, dependencies: domain.dependencies, blockers: [], merge_targets: [], taxonomy_type: "domain" });
    return response({});
  });
});
afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });

describe("Taxonomy Management", () => {
  it("requires an administrator key", () => {
    render(<TaxonomyManagementPage />);
    expect(screen.getByText("Unlock taxonomy management")).toBeTruthy();
  });

  it("loads the security domain tab and creates a new entry", async () => {
    render(<TaxonomyManagementPage />);
    fireEvent.change(screen.getByLabelText("Administrator API key"), { target: { value: "test-admin-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Open taxonomy management" }));
    await waitFor(() => expect(screen.getByText("Embedded Systems Security")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Add Security Domain" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Security Automation" } });
    fireEvent.click(screen.getByRole("button", { name: "Create entry" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining("/taxonomy/domain"), expect.objectContaining({ method: "POST" })));
    expect(screen.getByText("Security Domain created.")).toBeTruthy();
  });

  it("supports impact inspection and deactivation controls", async () => {
    render(<TaxonomyManagementPage />);
    fireEvent.change(screen.getByLabelText("Administrator API key"), { target: { value: "test-admin-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Open taxonomy management" }));
    await waitFor(() => expect(screen.getByText("Embedded Systems Security")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Impact" }));
    expect(await screen.findByText("DEPENDENCY IMPACT")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining("/deactivate"), expect.objectContaining({ method: "POST" })));
  });
});
