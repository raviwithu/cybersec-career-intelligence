import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setAdminSessionKey } from "../src/api";
import KnowledgeMapAdminPage, { domainTree, pendingIndex, possibleDuplicates } from "../src/KnowledgeMapAdminPage";
import KnowledgeMapPage from "../src/KnowledgeMapPage";
import KnowledgeReviewPage from "../src/KnowledgeReviewPage";
import { lineDiff } from "../src/knowledgeMapActions";

vi.mock("../src/KnowledgeMapGraph", () => ({ default: () => <div data-testid="graph-stub" /> }));
vi.mock("../src/KnowledgeDiagramCanvas", () => ({ default: () => <div data-testid="diagram-canvas" /> }));

const cloud = { node_type: "domain", id: 2, slug: "cloud-api-security", name: "Cloud API Security", child_domain_count: 0, placed_topic_count: 2 };
const embedded = { node_type: "domain", id: 5, slug: "embedded", name: "Embedded Systems Security", child_domain_count: 1, placed_topic_count: 0 };
const oauth = { id: 1, topic_key: "oauth-2", name: "OAuth 2.0", short_description: "", placement_count: 1 };
const jwt = { id: 7, topic_key: "jwt", name: "JSON Web Tokens", short_description: "", placement_count: 1 };
const adminTopic = (topic, extra = {}) => ({ id: topic.id, topic_key: topic.topic_key, name: topic.name, slug: topic.topic_key, description: "", sections: [], coverage: { topic_id: topic.id, topic_key: topic.topic_key, items: [], complete: false }, related_topics: [], level_expectations: [], last_updated: null, is_active: true, publication_status: "published", parent_topic_id: null, aliases: [], ...extra });
const DOMAINS = [{ id: 2, name: "Cloud API Security", parent_id: null, is_active: true, display_order: 1 }, { id: 5, name: "Embedded Systems Security", parent_id: null, is_active: true, display_order: 2 }, { id: 6, name: "Secure Boot", parent_id: 5, is_active: true, display_order: 0 }];
// GET /domains returns top-level domains with their sub-domains nested under children, like the real API.
const nest = (list, parentId = null) => list.filter((item) => item.parent_id === parentId && item.is_active).sort((a, b) => a.display_order - b.display_order).map((item) => ({ ...item, description: "", updated_at: `2026-10-30T00:00:0${item.version || 0}Z`, children: nest(list, item.id) }));
const mapDomain = (item) => ({ node_type: "domain", id: item.id, slug: `d-${item.id}`, name: item.name, child_domain_count: nest(domains, item.id).length, placed_topic_count: item.id === 2 ? 2 : 0 });
const LEVELS = [{ id: 1, name: "Junior", slug: "junior", career_track: "shared" }];

function json(body, status = 200) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });
}

let proposals;
let posted;
let domains;

function mockApi() {
  posted = [];
  domains = DOMAINS.map((item) => ({ ...item }));
  global.fetch = vi.fn((url, options = {}) => {
    const { pathname, searchParams } = new URL(url);
    const path = pathname.replace("/api/v1", "");
    if (options.method === "POST" && path === "/knowledge/proposals") {
      const body = JSON.parse(options.body);
      posted.push(body);
      return json({ id: 900 + posted.length, version: 1, status: "review", ...body }, 201);
    }
    if (options.method === "POST" && path === "/knowledge/admin/findings/31/map-suggestions") return json({ finding_id: 31, finding_name: "Experience securing cloud-native APIs", provider: "ollama", model_id: "test-model", warnings: ["Suggestion 3 was dropped: unknown topic 999."], suggestions: [
      { action: "PLACE_TOPIC", existing_topic_id: 1, name: null, domain_id: 2, map_branch: "security", rationale: "Employers expect OAuth.", related_topic_id: null, relationship_type: null, domain_name: "Cloud API Security", topic_name: "OAuth 2.0", related_topic_name: null, note: null },
      { action: "CREATE_TOPIC", existing_topic_id: null, name: "API Gateway Security", domain_id: 2, map_branch: "security", rationale: "Gateways appear in the finding.", related_topic_id: null, relationship_type: null, domain_name: "Cloud API Security", topic_name: null, related_topic_name: null, note: null },
    ] });
    if (options.method === "POST" && path.endsWith("/map-suggestions/submit")) { const body = JSON.parse(options.body); posted.push({ path, ...body }); return json({ created: body.suggestions.map((_, index) => ({ id: 700 + index })), errors: [] }); }
    if (options.method === "POST" && path === "/research/taxonomy/domain") {
      const body = JSON.parse(options.body);
      posted.push({ path, ...body });
      const created = { id: 60 + domains.length, name: body.name, parent_id: body.parent_id, is_active: true, display_order: 0 };
      domains.push(created);
      return json(created, 201);
    }
    const taxonomy = path.match(/^\/research\/taxonomy\/domain\/(\d+)(\/deactivate)?$/);
    if (taxonomy) {
      const item = domains.find((entry) => entry.id === Number(taxonomy[1]));
      const body = options.body ? JSON.parse(options.body) : {};
      posted.push({ path, method: options.method, ...body });
      if (options.method === "PATCH") Object.assign(item, body, { version: (item.version || 0) + 1 });
      if (taxonomy[2]) item.is_active = false;
      if (options.method === "DELETE") return json({ message: "Only unused taxonomy entries can be permanently deleted", dependencies: { knowledge_topics: 1 } }, 409).then((response) => ({ ...response, json: () => Promise.resolve({ detail: { message: "Only unused taxonomy entries can be permanently deleted" } }) }));
      return json(item);
    }
    if (options.method === "POST") { posted.push({ path, ...JSON.parse(options.body) }); return json({ id: 1, status: "approved", version: 2 }); }
    if (path === "/knowledge/admin/topics") return json([adminTopic(oauth, { related_topics: [{ id: 7, topic_key: "jwt", name: "JSON Web Tokens", relationship_type: "dependency", direction: "outgoing", label: "Depends on" }] }), adminTopic(jwt, { aliases: ["JWT"] })]);
    if (path === "/domains") return json(nest(domains));
    if (path === "/knowledge/admin/findings") return json([{ id: 31, candidate_name: "Experience securing cloud-native APIs", finding_type: "practical-capability", domain: "Cloud API Security", status: "published" }]);
    if (path === "/levels") return json(LEVELS);
    if (path === "/industries") return json([]);
    if (path === "/knowledge/admin/proposals") {
      const items = proposals.filter((item) => searchParams.get("group") !== "map" || item.map);
      return json({ items, total: items.length, counts: {} });
    }
    if (path.endsWith("/map-preview")) return json({ proposal_id: 50, action: "PLACE_TOPIC", status: "review", message: null, branches: [{ domain_id: 2, domain_name: "Cloud API Security", map_branch: "security", label: "Security", before: [{ topic_id: 7, name: "JSON Web Tokens" }], after: [{ topic_id: 7, name: "JSON Web Tokens" }, { topic_id: 1, name: "OAuth 2.0" }] }] });
    if (path === "/knowledge-map") return json({ root: { id: "root", name: "CyberSec Career Intelligence" }, domains: nest(domains).map(mapDomain) });
    if (path === "/knowledge-map/domains/2/children") return json({ domain: cloud, nodes: [{ node_type: "branch", domain_id: 2, branch: "foundations", label: "Foundations", topic_count: 2 }] });
    const children = path.match(/^\/knowledge-map\/domains\/(5|6|6\d)\/children$/);
    if (children) return json({ domain: mapDomain(domains.find((item) => item.id === Number(children[1]))), nodes: nest(domains, Number(children[1])).map(mapDomain) });
    if (path === "/knowledge-map/domains/2/branches/foundations/topics") return json({ domain_id: 2, branch: "foundations", label: "Foundations", items: [oauth, jwt], total: 2, offset: 0, limit: Number(searchParams.get("limit")) });
    if (path.startsWith("/knowledge-map/topics/")) return json([{ domain_path: [{ id: 2, name: "Cloud API Security" }], branch: "foundations", label: "Foundations", context_note: "Delegated access for cloud APIs." }, { domain_path: [{ id: 5, name: "Embedded Systems Security" }], branch: "security", label: "Security", context_note: "Device-to-cloud authorization." }]);
    if (path.startsWith("/knowledge/topics/")) return json({ ...adminTopic(oauth), description: "Delegated authorization." });
    throw new Error(`Unexpected request ${url}`);
  });
}

const treeItem = (name) => screen.findByRole("treeitem", { name: new RegExp(`^${name}`) });

async function openTopicActions() {
  render(<KnowledgeMapAdminPage onNavigate={() => {}} />);
  fireEvent.keyDown(await treeItem("Cloud API Security"), { key: "ArrowRight" });
  fireEvent.keyDown(await treeItem("Foundations"), { key: "ArrowRight" });
  fireEvent.keyDown(await treeItem("OAuth 2.0"), { key: "Enter" });
  return screen.findByRole("region", { name: "Propose changes to OAuth 2.0" });
}

function reason(form, text = "Better fit for this domain.") {
  fireEvent.change(within(form).getByRole("textbox", { name: "Change reason" }), { target: { value: text } });
}

beforeEach(() => {
  proposals = [];
  localStorage.setItem("cybersec-career-intelligence.knowledge-map-view", "list");
  window.location.hash = "#knowledge-map-admin";
  setAdminSessionKey("admin-key");
  mockApi();
});

afterEach(() => {
  sessionStorage.clear();
  vi.restoreAllMocks();
});

describe("Knowledge Map Management", () => {
  it("submits a move proposal with the right payload and change reason", async () => {
    const actions = await openTopicActions();
    fireEvent.click(within(actions).getByRole("button", { name: "Move topic" }));
    const form = within(actions).getByRole("form", { name: /Move out of/ });
    fireEvent.change(within(form).getByRole("combobox", { name: "Destination domain" }), { target: { value: "5" } });
    expect(within(form).getByRole("note").textContent).toContain("Secure Boot");
    fireEvent.change(within(form).getByRole("combobox", { name: "Branch" }), { target: { value: "security" } });
    fireEvent.click(within(form).getByRole("button", { name: "Submit for review" }));
    expect(await within(form).findByRole("alert")).toBeTruthy();
    expect(posted).toHaveLength(0);
    reason(form);
    fireEvent.click(within(form).getByRole("button", { name: "Submit for review" }));
    await within(form).findByText(/Proposal #901 submitted for review/);
    expect(posted[0]).toMatchObject({ action: "MOVE_TOPIC", topic_id: 1, source_type: "manual", change_reason: "Better fit for this domain.", proposed_content: { from: { domain_id: 2 }, to: { domain_id: 5, map_branch: "security" } } });
  });

  it("submits parent, relationship removal, career level and deactivation proposals", async () => {
    const actions = await openTopicActions();
    fireEvent.click(within(actions).getByRole("button", { name: "Set parent topic" }));
    let form = within(actions).getByRole("form", { name: "Set parent topic" });
    fireEvent.change(within(form).getByRole("combobox", { name: "Parent topic" }), { target: { value: "7" } });
    reason(form);
    fireEvent.click(within(form).getByRole("button", { name: "Submit for review" }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toMatchObject({ action: "SET_PARENT_TOPIC", topic_id: 1, proposed_content: { parent_topic_id: 7 } });

    fireEvent.click(within(actions).getByRole("button", { name: "Remove relationship" }));
    form = within(actions).getByRole("form", { name: "Remove relationship" });
    fireEvent.change(within(form).getByRole("combobox", { name: "Relationship" }), { target: { value: "dependency:7" } });
    reason(form);
    fireEvent.click(within(form).getByRole("button", { name: "Submit for review" }));
    await waitFor(() => expect(posted).toHaveLength(2));
    expect(posted[1]).toMatchObject({ action: "REMOVE_TOPIC_RELATIONSHIP", proposed_content: { target_topic_id: 7, relationship_type: "dependency" } });

    fireEvent.click(within(actions).getByRole("button", { name: "Career levels" }));
    form = within(actions).getByRole("form", { name: "Career level expectations" });
    fireEvent.change(within(form).getByRole("combobox", { name: "Career level" }), { target: { value: "1" } });
    fireEvent.change(within(form).getByRole("textbox", { name: "Knowledge" }), { target: { value: "Explain grants." } });
    fireEvent.change(within(form).getByRole("textbox", { name: "Practical skills" }), { target: { value: "Configure PKCE." } });
    reason(form);
    fireEvent.click(within(form).getByRole("button", { name: "Submit for review" }));
    await waitFor(() => expect(posted).toHaveLength(3));
    expect(posted[2]).toMatchObject({ action: "UPDATE_CAREER_LEVELS", proposed_content: { levels: [{ career_level_id: 1, industry_id: null, expectation: "Explain grants.", practical_capability: "Configure PKCE." }] } });

    fireEvent.click(within(actions).getByRole("button", { name: "Deactivate topic" }));
    form = within(actions).getByRole("form", { name: "Deactivate topic" });
    fireEvent.change(within(form).getByRole("combobox", { name: "Duplicate of (optional)" }), { target: { value: "7" } });
    reason(form);
    fireEvent.click(within(form).getByRole("button", { name: "Propose deactivation" }));
    await waitFor(() => expect(posted).toHaveLength(4));
    expect(posted[3]).toMatchObject({ action: "DEACTIVATE_TOPIC", proposed_content: { reason: "Duplicate of JSON Web Tokens (topic 7)." } });
  });

  it("reorders a branch with up and down buttons", async () => {
    render(<KnowledgeMapAdminPage onNavigate={() => {}} />);
    fireEvent.keyDown(await treeItem("Cloud API Security"), { key: "ArrowRight" });
    fireEvent.keyDown(await treeItem("Foundations"), { key: "Enter" });
    const form = await screen.findByRole("form", { name: "Reorder Foundations" });
    fireEvent.click(await within(form).findByRole("button", { name: "Move JSON Web Tokens up" }));
    reason(form);
    fireEvent.click(within(form).getByRole("button", { name: "Submit for review" }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toMatchObject({ action: "REORDER_TOPICS", proposed_content: { domain_id: 2, map_branch: "foundations", ordered_topic_ids: [7, 1] } });
  });

  it("warns about duplicates before creating a topic and sends placements with it", async () => {
    render(<KnowledgeMapAdminPage onNavigate={() => {}} />);
    const form = await screen.findByRole("form", { name: "New topic" });
    fireEvent.change(within(form).getByRole("textbox", { name: "Name" }), { target: { value: "jwt" } });
    expect(within(form).getByText("Same name, key or alias")).toBeTruthy();
    reason(form, "Missing topic.");
    fireEvent.click(within(form).getByRole("button", { name: "Submit for review" }));
    expect((await within(form).findByRole("alert")).textContent).toContain("already exists");
    expect(posted).toHaveLength(0);
    fireEvent.change(within(form).getByRole("textbox", { name: "Name" }), { target: { value: "Token Binding" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "Place in domain (optional)" }), { target: { value: "2" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "Branch" }), { target: { value: "security" } });
    fireEvent.click(within(form).getByRole("button", { name: "Submit for review" }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toMatchObject({ action: "CREATE_TOPIC", topic_name: "Token Binding", proposed_content: { topic: { name: "Token Binding" }, placements: [{ domain_id: 2, map_branch: "security" }] } });
  });

  it("reuses one topic in several domains with a context note, one proposal per domain", async () => {
    const actions = await openTopicActions();
    const form = within(actions).getByRole("form", { name: "Place topic" });
    const domainsList = within(form).getByRole("listbox", { name: "Domains (select one or more to reuse the topic)" });
    [...domainsList.options].forEach((option) => { option.selected = ["5", "6"].includes(option.value); });
    fireEvent.change(domainsList);
    expect(form.textContent).toContain("One shared topic, placed in 2 domains");
    fireEvent.change(within(form).getByRole("combobox", { name: "Branch" }), { target: { value: "vulnerabilities" } });
    fireEvent.change(within(form).getByRole("textbox", { name: "How it applies in these domains (optional, same note for each)" }), { target: { value: " Device tokens. " } });
    reason(form, "Reuse in embedded.");
    fireEvent.click(within(form).getByRole("button", { name: "Submit for review" }));
    expect((await within(form).findByRole("status")).textContent).toContain("Proposals #901, #902 submitted for review");
    expect(posted.map((item) => [item.action, item.topic_id, item.proposed_content])).toEqual([
      ["PLACE_TOPIC", 1, { domain_id: 5, map_branch: "vulnerabilities", context_note: "Device tokens." }],
      ["PLACE_TOPIC", 1, { domain_id: 6, map_branch: "vulnerabilities", context_note: "Device tokens." }],
    ]);
  });

  it("shows the note for the current domain and edits only that placement's note", async () => {
    const actions = await openTopicActions();
    const panel = screen.getAllByText("Delegated access for cloud APIs.")[0].closest(".km-topic-panel");
    expect(within(panel).getByText("In Cloud API Security")).toBeTruthy();
    expect(within(panel).getByText("Device-to-cloud authorization.")).toBeTruthy();
    fireEvent.click(within(actions).getByRole("button", { name: "Domain context" }));
    const form = within(actions).getByRole("form", { name: "How OAuth 2.0 applies in Cloud API Security" });
    const note = within(form).getByRole("textbox", { name: "Domain context note" });
    await waitFor(() => expect(note.value).toBe("Delegated access for cloud APIs."));
    fireEvent.change(note, { target: { value: "" } });
    reason(form, "Note no longer needed.");
    fireEvent.click(within(form).getByRole("button", { name: "Submit for review" }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toMatchObject({ action: "PLACE_TOPIC", topic_id: 1, proposed_content: { domain_id: 2, map_branch: "foundations", context_note: "" } });
  });

  it("adds a sub-domain under a child domain and shows it on the map", async () => {
    render(<KnowledgeMapAdminPage onNavigate={() => {}} />);
    fireEvent.keyDown(await treeItem("Embedded Systems Security"), { key: "ArrowRight" });
    fireEvent.keyDown(await treeItem("Secure Boot"), { key: "Enter" });
    const region = await screen.findByRole("region", { name: "Propose changes to Secure Boot" });
    const form = within(region).getByRole("form", { name: "Add sub-domain" });
    expect(form.textContent).toContain("Embedded Systems Security › Secure Boot");
    fireEvent.click(within(form).getByRole("button", { name: "Add sub-domain" }));
    expect((await within(form).findByRole("alert")).textContent).toContain("name is required");
    fireEvent.change(within(form).getByRole("textbox", { name: "Sub-domain name" }), { target: { value: "Measured Boot" } });
    fireEvent.click(within(form).getByRole("button", { name: "Add sub-domain" }));
    expect((await within(form).findByRole("status")).textContent).toContain("Measured Boot was added under Embedded Systems Security › Secure Boot");
    expect(posted).toEqual([{ path: "/research/taxonomy/domain", name: "Measured Boot", description: "", parent_id: 6 }]);
    expect(await treeItem("Measured Boot")).toBeTruthy();
    const placeIn = screen.getAllByRole("combobox", { name: "Place in domain (optional)" })[0];
    expect([...placeIn.options].map((option) => option.textContent.replace(/\u00a0/g, " "))).toContain("      ↳ Measured Boot");
  });

  it("adds a sub-domain from the top of the page with a chosen parent", async () => {
    render(<KnowledgeMapAdminPage onNavigate={() => {}} />);
    fireEvent.keyDown(await treeItem("Embedded Systems Security"), { key: "ArrowRight" });
    await treeItem("Secure Boot");
    const form = screen.getByRole("form", { name: "Add sub-domain" });
    fireEvent.change(within(form).getByRole("textbox", { name: "Sub-domain name" }), { target: { value: "Measured Boot" } });
    fireEvent.click(within(form).getByRole("button", { name: "Add sub-domain" }));
    expect((await within(form).findByRole("alert")).textContent).toContain("Choose the parent domain");
    fireEvent.change(within(form).getByRole("combobox", { name: "Parent domain" }), { target: { value: "6" } });
    expect(form.textContent).toContain("Adds a child domain under Embedded Systems Security › Secure Boot.");
    fireEvent.click(within(form).getByRole("button", { name: "Add sub-domain" }));
    expect((await within(form).findByRole("status")).textContent).toContain("Measured Boot was added under Embedded Systems Security › Secure Boot");
    expect(posted).toEqual([{ path: "/research/taxonomy/domain", name: "Measured Boot", description: "", parent_id: 6 }]);
    expect((await treeItem("Measured Boot")).getAttribute("aria-level")).toBe("4");
  });

  it("edits, moves, deactivates and refuses to delete a used sub-domain", async () => {
    render(<KnowledgeMapAdminPage onNavigate={() => {}} />);
    fireEvent.keyDown(await treeItem("Embedded Systems Security"), { key: "Enter" });
    let form = within(await screen.findByRole("region", { name: "Propose changes to Embedded Systems Security" })).getByRole("form", { name: "Edit domain" });
    expect([...within(form).getByRole("combobox", { name: "Parent domain" }).options].map((option) => option.textContent)).toEqual(["Top level (no parent)", "Cloud API Security"]);
    fireEvent.keyDown(await treeItem("Embedded Systems Security"), { key: "ArrowRight" });
    fireEvent.keyDown(await treeItem("Secure Boot"), { key: "Enter" });
    const region = await screen.findByRole("region", { name: "Propose changes to Secure Boot" });
    form = within(region).getByRole("form", { name: "Edit domain" });
    expect(within(form).getByRole("textbox", { name: "Domain name" }).value).toBe("Secure Boot");
    fireEvent.change(within(form).getByRole("textbox", { name: "Domain name" }), { target: { value: "Secure Boot Chain" } });
    fireEvent.change(within(form).getByRole("textbox", { name: "Description" }), { target: { value: "Boot integrity." } });
    fireEvent.change(within(form).getByRole("combobox", { name: "Parent domain" }), { target: { value: "" } });
    fireEvent.change(within(form).getByRole("spinbutton", { name: "Display order" }), { target: { value: "3" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save domain" }));
    expect((await within(form).findByRole("status")).textContent).toContain("Secure Boot Chain was saved.");
    expect(posted).toEqual([{ path: "/research/taxonomy/domain/6", method: "PATCH", name: "Secure Boot Chain", description: "Boot integrity.", parent_id: null, display_order: 3, expected_updated_at: "2026-10-30T00:00:00Z" }]);
    await waitFor(() => expect(screen.getAllByRole("treeitem", { name: /^Secure Boot Chain/ }).map((item) => item.getAttribute("aria-level"))).toEqual(["2"]));

    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(within(form).getByRole("button", { name: "Delete if unused" }));
    expect((await within(form).findByRole("alert")).textContent).toContain("Only unused taxonomy entries can be permanently deleted");
    fireEvent.click(within(form).getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(within(region).getAllByRole("status").map((item) => item.textContent).join(" ")).toContain("Secure Boot Chain was deactivated"));
    expect(within(region).queryByRole("form", { name: "Edit domain" })).toBeNull();
    expect(posted.at(-1)).toMatchObject({ path: "/research/taxonomy/domain/6/deactivate", method: "POST" });
    await waitFor(() => expect(screen.queryByRole("treeitem", { name: /^Secure Boot Chain/ })).toBeNull());
  });

  it("shows Pending badges in the admin view only", async () => {
    proposals = [{ id: 50, map: true, action: "PLACE_TOPIC", status: "review", topic_id: 1, topic_key: "oauth-2", proposed_content: { domain_id: 2, map_branch: "foundations" } }];
    const { unmount } = render(<KnowledgeMapAdminPage onNavigate={() => {}} />);
    fireEvent.keyDown(await treeItem("Cloud API Security"), { key: "ArrowRight" });
    fireEvent.keyDown(await treeItem("Foundations"), { key: "ArrowRight" });
    expect(within(await treeItem("OAuth 2.0")).getAllByText("Pending")).toHaveLength(1);
    expect(within(await treeItem("Foundations")).getAllByText("Pending").length).toBeGreaterThan(0);
    unmount();

    window.location.hash = "#knowledge-map";
    render(<KnowledgeMapPage />);
    fireEvent.keyDown(await treeItem("Cloud API Security"), { key: "ArrowRight" });
    fireEvent.keyDown(await treeItem("Foundations"), { key: "ArrowRight" });
    await treeItem("OAuth 2.0");
    expect(screen.queryByText("Pending")).toBeNull();
  });
});

describe("AI map suggestions", () => {
  it("asks for suggestions, then submits only the selected ones with schema fields", async () => {
    render(<KnowledgeMapAdminPage onNavigate={() => {}} />);
    const panel = await screen.findByRole("region", { name: "AI map suggestions" });
    fireEvent.change(await within(panel).findByRole("combobox", { name: "Approved finding" }), { target: { value: "31" } });
    fireEvent.click(within(panel).getByRole("button", { name: "Suggest map changes" }));
    const create = await within(panel).findByRole("checkbox", { name: /Create topic .*API Gateway Security/ });
    expect(within(panel).getByText("1 suggestions were dropped")).toBeTruthy();
    expect(posted).toHaveLength(0);
    fireEvent.click(create);
    fireEvent.click(within(panel).getByRole("button", { name: "Submit 1 selected as proposals" }));
    expect(await within(panel).findByText(/1 proposal submitted for review \(#700\)/)).toBeTruthy();
    expect(posted[0].path).toBe("/knowledge/admin/findings/31/map-suggestions/submit");
    expect(posted[0].suggestions).toEqual([{ action: "CREATE_TOPIC", existing_topic_id: null, name: "API Gateway Security", domain_id: 2, map_branch: "security", rationale: "Gateways appear in the finding.", related_topic_id: null, relationship_type: null }]);
  });
});

describe("Knowledge Review mind map tab", () => {
  it("lists map proposals, shows before and after, then reviews and publishes", async () => {
    proposals = [
      { id: 50, map: true, schema_version: "1.0", source_type: "manual", topic_id: 1, topic_key: "oauth-2", action: "PLACE_TOPIC", section: null, status: "review", version: 1, base_section_version: 3, original_content: { placement: null }, proposed_content: { domain_id: 2, map_branch: "security", display_order: null }, change_reason: "Belongs in Security.", created_at: "2026-10-30T10:00:00Z", updated_at: "2026-10-30T10:00:00Z", submitted_by: "administrator", references: [], review_decisions: [] },
      { id: 51, map: false, schema_version: "1.0", source_type: "manual", topic_id: 1, topic_key: "oauth-2", action: "UPDATE_SECTION", section: "overview", status: "review", version: 1, base_section_version: 1, original_content: {}, proposed_content: { short_description: "x" }, change_reason: "", created_at: "2026-10-30T10:00:00Z", updated_at: "2026-10-30T10:00:00Z", references: [], review_decisions: [] },
    ];
    render(<KnowledgeReviewPage />);
    expect(await screen.findByText("2 review items")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Mind Map Changes" }));
    expect(await screen.findByText("1 review items")).toBeTruthy();
    expect(global.fetch.mock.calls.some(([url]) => url.includes("group=map"))).toBe(true);
    expect(screen.getByText("Belongs in Security.")).toBeTruthy();
    expect(screen.getByText(/by administrator/)).toBeTruthy();
    const diff = screen.getByLabelText("Before and after differences");
    expect(diff.querySelector(".kr-diff-added").textContent).toContain("+ ");
    const branch = await screen.findByText("Cloud API Security › Security");
    expect(within(branch.closest("article")).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["JSON Web Tokens", "JSON Web Tokens", "OAuth 2.0"]);

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(posted.some((item) => item.path === "/knowledge/admin/proposals/50/review" && item.action === "approve")).toBe(true));
    proposals[0] = { ...proposals[0], status: "approved", version: 2 };
    fireEvent.click(screen.getByRole("tab", { name: "All proposals" }));
    fireEvent.click(screen.getByRole("tab", { name: "Mind Map Changes" }));
    fireEvent.click(await screen.findByRole("button", { name: "Publish approved proposal" }));
    await waitFor(() => expect(posted.some((item) => item.path === "/knowledge/admin/proposals/50/publish" && item.expected_version === 2 && item.confirm === true)).toBe(true));
  });

  it("keeps the existing all-proposals view for section changes", async () => {
    proposals = [{ id: 51, map: false, schema_version: "1.0", source_type: "manual", topic_id: 1, topic_key: "oauth-2", action: "UPDATE_SECTION", section: "overview", status: "review", version: 1, base_section_version: 1, original_content: { short_description: "old" }, proposed_content: { short_description: "new" }, change_reason: "", created_at: "2026-10-30T10:00:00Z", updated_at: "2026-10-30T10:00:00Z", references: [], review_decisions: [] }];
    render(<KnowledgeReviewPage />);
    expect(await screen.findByText("Existing published content")).toBeTruthy();
    expect(global.fetch.mock.calls.some(([url]) => url.includes("group=map"))).toBe(false);
    expect(screen.queryByLabelText("Before and after differences")).toBeNull();
  });
});

describe("knowledge map admin helpers", () => {
  it("indexes pending topics and branches from open proposals only", () => {
    const { topics, branches } = pendingIndex([
      { id: 1, status: "review", topic_id: 4, action: "MOVE_TOPIC", proposed_content: { from: { domain_id: 2 }, to: { domain_id: 5, map_branch: "security" } } },
      { id: 2, status: "published", topic_id: 9, action: "PLACE_TOPIC", proposed_content: { domain_id: 2, map_branch: "foundations" } },
      { id: 3, status: "approved", topic_id: null, action: "CREATE_TOPIC", proposed_content: { placements: [{ domain_id: 6, map_branch: "vulnerabilities" }] } },
    ]);
    expect([...topics.keys()]).toEqual([4]);
    expect([...branches]).toEqual(["branch:5:security", "branch:6:vulnerabilities"]);
  });

  it("orders domains as a tree of any depth", () => {
    const tree = domainTree([{ id: 3, name: "Leaf", parent_id: 2 }, { id: 2, name: "Child", parent_id: 1 }, { id: 4, name: "Another root", parent_id: null }, { id: 1, name: "Root", parent_id: null }, { id: 9, name: "Orphan", parent_id: 99 }]);
    expect(tree.map((item) => [item.name, item.depth, item.path.join(" › ")])).toEqual([["Another root", 0, "Another root"], ["Orphan", 0, "Orphan"], ["Root", 0, "Root"], ["Child", 1, "Root › Child"], ["Leaf", 2, "Root › Child › Leaf"]]);
  });

  it("flags exact and similar duplicates", () => {
    const topics = [adminTopic(jwt, { aliases: ["JWT"] }), adminTopic(oauth)];
    expect(possibleDuplicates(topics, "J.W.T")).toEqual([{ topic: expect.objectContaining({ id: 7 }), exact: true }]);
    expect(possibleDuplicates(topics, "OAuth")[0]).toMatchObject({ exact: false });
    expect(possibleDuplicates(topics, "ab")).toEqual([]);
  });

  it("diffs lines", () => {
    expect(lineDiff({ a: 1 }, { a: 2 }).map((row) => row.kind)).toEqual(["same", "removed", "added", "same"]);
  });
});
