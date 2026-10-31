import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import KnowledgeMapPage from "../src/KnowledgeMapPage";
import SidebarNavigation, { getViewFromLocation } from "../src/SidebarNavigation";
import { applyDomainChildren, applyRoot, applyTopicPage, branchNodeId, collapse, domainNodeId, ensureTopic, expand, initialMapState, layoutTree, pathTo, topicNodeId, visibleAncestor, visibleRows, visibleTree } from "../src/knowledgeMapModel";

// React Flow needs real layout APIs that jsdom lacks; behaviour is tested through the list view and pure helpers.
vi.mock("../src/KnowledgeMapGraph", () => ({ default: () => <div data-testid="graph-stub" /> }));

const domain = (id, name, childCount = 0, topicCount = 0) => ({ node_type: "domain", id, slug: name.toLowerCase().replace(/ /g, "-"), name, child_domain_count: childCount, placed_topic_count: topicCount });
const branch = (domainId, key, label, count) => ({ node_type: "branch", domain_id: domainId, branch: key, label, topic_count: count });
const topic = (id, key, name, placementCount = 1) => ({ id, topic_key: key, name, short_description: `${name} summary.`, placement_count: placementCount, has_children: false });
const placement = (path, key, label) => ({ domain_path: path.map(([id, name]) => ({ id, name })), branch: key, label });

const cloud = domain(2, "Cloud API Security", 0, 3);
const embedded = domain(5, "Embedded Systems Security", 1, 2);
const empty = domain(9, "Quantum Readiness", 0, 0);
const secureBoot = domain(6, "Secure Boot", 0, 1);
const oauth = topic(1, "oauth-2", "OAuth 2.0", 2);
const oauthPlacements = [placement([[2, "Cloud API Security"]], "foundations", "Foundations"), placement([[5, "Embedded Systems Security"], [6, "Secure Boot"]], "foundations", "Foundations")];
const VULNERABILITY_TOTAL = 120;
const vulnerability = (index) => topic(100 + index, `vuln-${index}`, `Vulnerability ${String(index).padStart(3, "0")}`);

function routes(url) {
  const { pathname, searchParams } = new URL(url);
  const path = pathname.replace("/api/v1", "");
  if (path === "/knowledge-map") return { root: { id: "root", name: "CyberSec Career Intelligence" }, domains: [cloud, embedded, empty] };
  if (path === "/knowledge-map/domains/2/children") return { domain: cloud, nodes: [branch(2, "foundations", "Foundations", 1), branch(2, "vulnerabilities", "Common Vulnerabilities", VULNERABILITY_TOTAL)] };
  if (path === "/knowledge-map/domains/5/children") return { domain: embedded, nodes: [secureBoot, branch(5, "security", "Security", 1)] };
  if (path === "/knowledge-map/domains/6/children") return { domain: secureBoot, nodes: [branch(6, "foundations", "Foundations", 1)] };
  if (path === "/knowledge-map/domains/9/children") return { domain: empty, nodes: [] };
  const topics = path.match(/^\/knowledge-map\/domains\/(\d+)\/branches\/(\w+)\/topics$/);
  if (topics) {
    const offset = Number(searchParams.get("offset") || 0);
    const limit = Number(searchParams.get("limit") || 50);
    const all = topics[2] === "vulnerabilities" ? Array.from({ length: VULNERABILITY_TOTAL }, (_, index) => vulnerability(index)) : topics[2] === "security" ? [topic(3, "secure-boot-chain", "Secure Boot Chain")] : [oauth];
    return { domain_id: Number(topics[1]), branch: topics[2], label: topics[2], items: all.slice(offset, offset + limit), total: all.length, offset, limit };
  }
  if (path === "/knowledge-map/topics/oauth-2/placements") return oauthPlacements;
  if (path.startsWith("/knowledge-map/topics/")) return [];
  if (path === "/knowledge/topics/oauth-2") return { id: 1, topic_key: "oauth-2", name: "OAuth 2.0", description: "Delegated authorization." };
  if (path === "/knowledge-map/search") {
    const q = searchParams.get("q").toLowerCase();
    if (q.startsWith("idor")) return { query: q, items: [{ id: 400, topic_key: "idor", name: "IDOR / BOLA", short_description: "Object-level authorization flaws.", placements: [placement([[2, "Cloud API Security"]], "vulnerabilities", "Common Vulnerabilities")] }] };
    if (q.startsWith("oauth")) return { query: q, items: [{ ...oauth, placements: oauthPlacements }] };
    return { query: q, items: [] };
  }
  throw new Error(`Unexpected request ${url}`);
}

function mockApi(override) {
  global.fetch = vi.fn((url) => {
    const result = override?.(url);
    if (result) return result;
    try { return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(routes(url)) }); } catch (error) { return Promise.reject(error); }
  });
  return global.fetch;
}

function requested(fetchMock, fragment) {
  return fetchMock.mock.calls.some(([url]) => url.includes(fragment));
}

const item = (name) => screen.getByRole("treeitem", { name: new RegExp(`^${name}`) });
const findItem = (name) => screen.findByRole("treeitem", { name: new RegExp(`^${name}`) });
const press = (element, key) => fireEvent.keyDown(element, { key });
const groupOf = (treeitem) => within(treeitem).getByRole("group");

async function renderMap() {
  render(<KnowledgeMapPage />);
  return findItem("Cloud API Security");
}

beforeEach(() => {
  localStorage.setItem("cybersec-career-intelligence.knowledge-map-view", "list");
  window.location.hash = "#knowledge-map";
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  window.location.hash = "";
});

describe("Security Knowledge Map page", () => {
  it("renders the root and the domains the API returns", async () => {
    mockApi();
    await renderMap();
    expect(item("CyberSec Career Intelligence").getAttribute("aria-expanded")).toBe("true");
    const names = within(groupOf(item("CyberSec Career Intelligence"))).getAllByRole("treeitem").map((element) => element.textContent);
    expect(names.map((name) => name.replace(/\d+ topics$/, "").replace(/^[^A-Z]+/, ""))).toEqual(["Cloud API Security", "Embedded Systems Security", "Quantum Readiness"]);
    expect(screen.queryByTestId("graph-stub")).toBeNull();
  });

  it("expands a domain into child domains first, then its branches", async () => {
    const fetchMock = mockApi();
    const embeddedItem = (await renderMap(), item("Embedded Systems Security"));
    expect(requested(fetchMock, "/domains/5/children")).toBe(false);
    press(embeddedItem, "ArrowRight");
    await findItem("Secure Boot");
    expect(embeddedItem.getAttribute("aria-expanded")).toBe("true");
    const children = within(groupOf(embeddedItem)).getAllByRole("treeitem").filter((element) => element.getAttribute("aria-level") === "3");
    expect(children.map((element) => element.textContent)).toEqual([expect.stringContaining("Secure Boot"), expect.stringContaining("Security")]);
  });

  it("keeps branches scoped to the domain that was expanded", async () => {
    mockApi();
    await renderMap();
    press(item("Cloud API Security"), "ArrowRight");
    press(item("Embedded Systems Security"), "ArrowRight");
    await findItem("Secure Boot");
    await findItem("Common Vulnerabilities");
    const cloudBranches = within(groupOf(item("Cloud API Security"))).getAllByRole("treeitem").map((element) => element.textContent);
    expect(cloudBranches.some((text) => text.includes("Foundations"))).toBe(true);
    expect(cloudBranches.some((text) => text.includes("Common Vulnerabilities"))).toBe(true);
    expect(cloudBranches.some((text) => /^\W*Security/.test(text))).toBe(false);
    expect(within(groupOf(item("Embedded Systems Security"))).queryByRole("treeitem", { name: /Common Vulnerabilities/ })).toBeNull();
  });

  it("shows an empty state for a domain with no published topics", async () => {
    mockApi();
    await renderMap();
    press(item("Quantum Readiness"), "ArrowRight");
    expect(await findItem("No published topics yet")).toBeTruthy();
  });

  it("lists branch topics 50 at a time and loads the next page on request", async () => {
    const fetchMock = mockApi();
    await renderMap();
    press(item("Cloud API Security"), "ArrowRight");
    press(await findItem("Common Vulnerabilities"), "ArrowRight");
    await findItem("Vulnerability 049");
    expect(screen.queryByRole("treeitem", { name: /^Vulnerability 050/ })).toBeNull();
    press(item("Load more \\(70 remaining\\)"), "Enter");
    await findItem("Vulnerability 099");
    expect(requested(fetchMock, "/branches/vulnerabilities/topics?offset=50&limit=50")).toBe(true);
    expect(item("Load more \\(20 remaining\\)")).toBeTruthy();
  });

  it("selecting a topic opens the details panel and the breadcrumb", async () => {
    mockApi();
    await renderMap();
    press(item("Cloud API Security"), "ArrowRight");
    press(await findItem("Foundations"), "ArrowRight");
    press(await findItem("OAuth 2.0"), "Enter");
    const details = screen.getByRole("complementary", { name: "Selected node details" });
    expect(within(details).getByRole("heading", { name: "OAuth 2.0" })).toBeTruthy();
    expect(await within(details).findByText("Delegated authorization.")).toBeTruthy();
    expect(await within(details).findByRole("button", { name: "Embedded Systems Security › Secure Boot › Foundations" })).toBeTruthy();
    const crumbs = within(screen.getByRole("navigation", { name: "Selected path" })).getAllByRole("listitem").map((element) => element.textContent);
    expect(crumbs).toEqual(["CyberSec Career Intelligence", "Cloud API Security", "Foundations", "OAuth 2.0"]);
    expect(window.location.hash).toBe("#knowledge-map?topic=oauth-2");
    fireEvent.click(within(screen.getByRole("navigation", { name: "Selected path" })).getByRole("button", { name: "Cloud API Security" }));
    expect(within(details).getByRole("heading", { name: "Cloud API Security" })).toBeTruthy();
  });

  it("search reveals only the path to the result, even beyond the loaded page", async () => {
    const fetchMock = mockApi();
    await renderMap();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "idor" } });
    fireEvent.click(await screen.findByRole("button", { name: /IDOR \/ BOLA/ }));
    const idor = await findItem("IDOR / BOLA");
    expect(idor.getAttribute("aria-selected")).toBe("true");
    expect(item("Cloud API Security").getAttribute("aria-expanded")).toBe("true");
    expect(item("Common Vulnerabilities").getAttribute("aria-expanded")).toBe("true");
    expect(item("Foundations").getAttribute("aria-expanded")).toBe("false");
    expect(item("Embedded Systems Security").getAttribute("aria-expanded")).toBe("false");
    expect(requested(fetchMock, "/domains/5/children")).toBe(false);
    expect(requested(fetchMock, "/branches/foundations/")).toBe(false);
  });

  it("asks which path to use when a search result has several placements", async () => {
    mockApi();
    await renderMap();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "oauth" } });
    fireEvent.click(await screen.findByRole("button", { name: /OAuth 2\.0.*2 locations/ }));
    fireEvent.click(within(screen.getByRole("group", { name: "Choose where to show OAuth 2.0" })).getByRole("button", { name: "Embedded Systems Security › Secure Boot › Foundations" }));
    await waitFor(() => expect(item("OAuth 2.0").getAttribute("aria-selected")).toBe("true"));
    expect(item("Secure Boot").getAttribute("aria-expanded")).toBe("true");
    expect(item("Cloud API Security").getAttribute("aria-expanded")).toBe("false");
  });

  it("expands a topic into its child topics, at any depth", async () => {
    const children = { 1: [{ ...topic(11, "pkce", "PKCE"), has_children: true }], 11: [topic(12, "code-verifier", "Code Verifier")] };
    mockApi((url) => {
      const { pathname } = new URL(url);
      const nested = pathname.match(/\/knowledge-map\/domains\/2\/branches\/foundations\/topics\/(\d+)\/children$/);
      if (nested) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ topic_id: Number(nested[1]), domain_id: 2, branch: "foundations", items: children[nested[1]] }) });
      if (pathname.endsWith("/domains/2/branches/foundations/topics")) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ domain_id: 2, branch: "foundations", label: "Foundations", items: [{ ...oauth, has_children: true }], total: 1, offset: 0, limit: 50 }) });
      return null;
    });
    press(await renderMap(), "ArrowRight");
    press(await findItem("Foundations"), "ArrowRight");
    const parent = await findItem("OAuth 2.0");
    expect(parent.getAttribute("aria-expanded")).toBe("false");
    press(parent, "ArrowRight");
    const pkce = await findItem("PKCE");
    expect(pkce.getAttribute("aria-level")).toBe(String(Number(parent.getAttribute("aria-level")) + 1));
    press(pkce, "ArrowRight");
    expect((await findItem("Code Verifier")).getAttribute("aria-level")).toBe(String(Number(pkce.getAttribute("aria-level")) + 1));
    expect(item("Code Verifier").getAttribute("aria-expanded")).toBeNull();
  });

  it("search opens a nested topic under its parent topics", async () => {
    const pkcePlacement = { ...placement([[2, "Cloud API Security"]], "foundations", "Foundations"), ancestors: [{ id: 1, topic_key: "oauth-2", name: "OAuth 2.0" }] };
    mockApi((url) => {
      const { pathname, searchParams } = new URL(url);
      const reply = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
      if (pathname.endsWith("/knowledge-map/search") && searchParams.get("q") === "pkce") return reply({ query: "pkce", items: [{ ...topic(11, "pkce", "PKCE"), placements: [pkcePlacement] }] });
      if (pathname.endsWith("/domains/2/branches/foundations/topics/1/children")) return reply({ topic_id: 1, domain_id: 2, branch: "foundations", items: [topic(11, "pkce", "PKCE")] });
      if (pathname.endsWith("/domains/2/branches/foundations/topics")) return reply({ domain_id: 2, branch: "foundations", label: "Foundations", items: [{ ...oauth, has_children: true }], total: 1, offset: 0, limit: 50 });
      return null;
    });
    await renderMap();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "pkce" } });
    fireEvent.click(await screen.findByRole("button", { name: /PKCE/ }));
    await waitFor(() => expect(item("PKCE").getAttribute("aria-selected")).toBe("true"));
    expect(item("OAuth 2.0").getAttribute("aria-expanded")).toBe("true");
    expect(screen.getAllByRole("treeitem", { name: /^PKCE/ })).toHaveLength(1);
  });

  it("opens a deep-linked topic", async () => {
    window.location.hash = "#knowledge-map?topic=oauth-2";
    mockApi();
    render(<KnowledgeMapPage />);
    await waitFor(() => expect(item("OAuth 2.0").getAttribute("aria-selected")).toBe("true"));
    expect(window.location.hash).toBe("#knowledge-map?topic=oauth-2");
  });

  it("a related topic in the detail panel navigates the map to that topic", async () => {
    window.location.hash = "#knowledge-map?topic=oauth-2";
    const json = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    mockApi((url) => {
      if (url.endsWith("/knowledge/topics/oauth-2")) return json({ id: 1, topic_key: "oauth-2", name: "OAuth 2.0", description: "Delegated authorization.", sections: [], level_expectations: [], related_topics: [{ id: 3, topic_key: "secure-boot-chain", name: "Secure Boot Chain", relationship_type: "dependency", direction: "incoming", label: "Used by" }] });
      if (url.endsWith("/knowledge/topics/secure-boot-chain")) return json({ id: 3, topic_key: "secure-boot-chain", name: "Secure Boot Chain", description: "", sections: [], level_expectations: [], related_topics: [] });
      if (url.endsWith("/knowledge-map/topics/secure-boot-chain/placements")) return json([placement([[5, "Embedded Systems Security"]], "security", "Security")]);
      return null;
    });
    render(<KnowledgeMapPage />);
    const details = await screen.findByRole("complementary", { name: "Selected node details" });
    fireEvent.click(await within(details).findByRole("tab", { name: "Related Topics" }));
    expect(within(details).getByText("Used by")).toBeTruthy();
    fireEvent.click(within(details).getByRole("button", { name: "Secure Boot Chain" }));
    await waitFor(() => expect(item("Secure Boot Chain").getAttribute("aria-selected")).toBe("true"));
    expect(window.location.hash).toBe("#knowledge-map?topic=secure-boot-chain");
    expect(item("Embedded Systems Security").getAttribute("aria-expanded")).toBe("true");
  });

  it("supports tree keyboard navigation with ARIA levels", async () => {
    mockApi();
    await renderMap();
    const root = item("CyberSec Career Intelligence");
    expect(screen.getByRole("tree").getAttribute("aria-label")).toBe("Security Knowledge Map");
    expect(root.getAttribute("aria-level")).toBe("1");
    expect(item("Cloud API Security").getAttribute("aria-level")).toBe("2");
    expect(item("Cloud API Security").getAttribute("aria-expanded")).toBe("false");
    root.focus();
    press(root, "ArrowDown");
    expect(document.activeElement).toBe(item("Cloud API Security"));
    press(document.activeElement, "End");
    expect(document.activeElement).toBe(item("Quantum Readiness"));
    press(document.activeElement, "Home");
    expect(document.activeElement).toBe(root);
    press(root, "ArrowRight");
    expect(document.activeElement).toBe(item("Cloud API Security"));
    press(document.activeElement, "ArrowRight");
    await findItem("Foundations");
    press(document.activeElement, "ArrowRight");
    expect(document.activeElement).toBe(item("Foundations"));
    press(document.activeElement, "ArrowLeft");
    expect(document.activeElement).toBe(item("Cloud API Security"));
    press(document.activeElement, "ArrowLeft");
    expect(item("Cloud API Security").getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("treeitem", { name: /^Foundations/ })).toBeNull();
    expect(item("Cloud API Security").tabIndex).toBe(0);
  });

  it("collapse hides descendants and Go to parent selects the parent", async () => {
    mockApi();
    await renderMap();
    press(item("Cloud API Security"), "ArrowRight");
    press(await findItem("Foundations"), "ArrowRight");
    press(await findItem("OAuth 2.0"), "Enter");
    fireEvent.click(screen.getByRole("button", { name: "Go to parent" }));
    expect(item("Foundations").getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Go to parent" }));
    expect(item("Cloud API Security").getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Collapse" }));
    expect(screen.queryByRole("treeitem", { name: /^Foundations/ })).toBeNull();
    expect(screen.queryByRole("treeitem", { name: /^OAuth/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    expect(item("OAuth 2.0")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Collapse all" }));
    expect(screen.queryByRole("treeitem", { name: /^Foundations/ })).toBeNull();
    expect(item("Cloud API Security").getAttribute("aria-selected")).toBe("true");
  });

  it("expand children opens one level below the selection", async () => {
    mockApi();
    await renderMap();
    fireEvent.click(screen.getByRole("button", { name: "Expand children" }));
    await findItem("Secure Boot");
    await findItem("Common Vulnerabilities");
    expect(item("Embedded Systems Security").getAttribute("aria-expanded")).toBe("true");
    expect(item("Secure Boot").getAttribute("aria-expanded")).toBe("false");
  });

  it("shows the error state and retries", async () => {
    let failures = 1;
    mockApi((url) => (url.endsWith("/knowledge-map") && failures-- > 0 ? Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: "Map unavailable" }) }) : null));
    render(<KnowledgeMapPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("Map unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await findItem("Cloud API Security")).toBeTruthy();
  });

  it("shows an inline retry when a branch fails to load", async () => {
    let failures = 1;
    mockApi((url) => (url.includes("/domains/2/children") && failures-- > 0 ? Promise.reject(new Error("offline")) : null));
    await renderMap();
    press(item("Cloud API Security"), "ArrowRight");
    press(await findItem("Could not load. Retry"), "Enter");
    expect(await findItem("Foundations")).toBeTruthy();
  });

  it("remembers the Graph or List choice", async () => {
    mockApi();
    await renderMap();
    fireEvent.click(screen.getByRole("button", { name: "Graph" }));
    expect(await screen.findByTestId("graph-stub")).toBeTruthy();
    expect(localStorage.getItem("cybersec-career-intelligence.knowledge-map-view")).toBe("graph");
    expect(screen.getByRole("button", { name: "Zoom in" }).disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "List" }));
    expect(screen.getByRole("button", { name: "Zoom in" }).disabled).toBe(true);
  });

  it("stays responsive with a 1,000-topic branch loaded page by page", async () => {
    const total = 1000;
    mockApi((url) => {
      const match = url.match(/branches\/vulnerabilities\/topics\?offset=(\d+)&limit=(\d+)/);
      if (!match) return null;
      const [offset, limit] = [Number(match[1]), Number(match[2])];
      const items = Array.from({ length: Math.min(limit, total - offset) }, (_, index) => vulnerability(offset + index));
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ domain_id: 2, branch: "vulnerabilities", label: "Common Vulnerabilities", items, total, offset, limit }) });
    });
    // Role queries compute accessible names over every nested item, which is quadratic here; look rows up by label.
    const byLabel = (text) => [...document.querySelectorAll(".km-tree-label")].find((element) => element.textContent === text)?.closest("[role=treeitem]");
    await renderMap();
    press(item("Cloud API Security"), "ArrowRight");
    press(await findItem("Common Vulnerabilities"), "ArrowRight");
    const pageTimes = [];
    for (let page = 1; page < total / 50; page += 1) {
      const more = await waitFor(() => { const element = byLabel(`Load more (${total - page * 50} remaining)`); if (!element) throw new Error("not loaded"); return element; });
      const started = performance.now();
      press(more, "Enter");
      await waitFor(() => { if (!byLabel(`Vulnerability ${String(page * 50 + 49).padStart(3, "0")}`)) throw new Error("not loaded"); });
      pageTimes.push(performance.now() - started);
    }
    const last = byLabel("Vulnerability 999");
    const started = performance.now();
    press(last, "Enter");
    expect(last.getAttribute("aria-selected")).toBe("true");
    const elapsed = performance.now() - started;
    console.info(`1,000 topics: slowest page load-and-render ${Math.max(...pageTimes).toFixed(0)} ms; selecting a topic ${elapsed.toFixed(1)} ms`);
    expect(elapsed).toBeLessThan(1000);
    expect(document.querySelectorAll(".km-tree-row.km-node-topic").length).toBe(total);
    expect([...document.querySelectorAll(".km-tree-label")].some((element) => element.textContent.startsWith("Load more"))).toBe(false);
  }, 60000);
});

describe("Security Knowledge Map navigation", () => {
  it("lists the map in Explore after Knowledge Base", () => {
    render(<SidebarNavigation view="knowledge-map" mobileOpen={false} onNavigate={vi.fn()} onClose={vi.fn()} />);
    const labels = within(document.getElementById("nav-group-explore")).getAllByRole("button").map((element) => element.textContent);
    expect(labels.indexOf("⌬Security Knowledge Map")).toBe(labels.indexOf("▤Knowledge Base") + 1);
    expect(screen.getByRole("button", { name: "Security Knowledge Map" }).getAttribute("aria-current")).toBe("page");
  });

  it("reads the view from a deep link that carries a topic", () => {
    window.location.hash = "#knowledge-map?topic=oauth-2";
    expect(getViewFromLocation()).toBe("knowledge-map");
  });
});

describe("knowledge map model", () => {
  function loadedState() {
    let state = applyRoot(initialMapState(), { root: { id: "root", name: "Root" }, domains: [cloud, embedded] });
    state = applyDomainChildren(state, domainNodeId(2), { nodes: [branch(2, "foundations", "Foundations", 1), branch(2, "vulnerabilities", "Common Vulnerabilities", 3)] });
    return expand(state, [domainNodeId(2)]);
  }

  it("lays the visible tree out left to right from structure alone", () => {
    const state = loadedState();
    const layout = layoutTree(visibleTree(state));
    const x = Object.fromEntries(layout.positions.map((position) => [position.id, position.x]));
    expect(x.root).toBeLessThan(x[domainNodeId(2)]);
    expect(x[domainNodeId(2)]).toBeLessThan(x[branchNodeId(2, "foundations")]);
    expect(layout.edges).toContainEqual(expect.objectContaining({ source: domainNodeId(2), target: branchNodeId(2, "vulnerabilities") }));
    expect(layout.positions.map((position) => position.id)).not.toContain(domainNodeId(6));
  });

  it("pages topics without duplicates and keeps revealed topics", () => {
    const branchId = branchNodeId(2, "vulnerabilities");
    let state = applyTopicPage(loadedState(), branchId, { items: [vulnerability(0)], total: 3, offset: 0, limit: 1 });
    state = ensureTopic(state, branchId, vulnerability(2));
    state = applyTopicPage(state, branchId, { items: [vulnerability(1), vulnerability(2)], total: 3, offset: 1, limit: 2 });
    expect(state.children[branchId]).toEqual([0, 2, 1].map((index) => topicNodeId(2, "vulnerabilities", `vuln-${index}`)));
    expect(pathTo(state, topicNodeId(2, "vulnerabilities", "vuln-1"))).toEqual(["root", domainNodeId(2), branchId, topicNodeId(2, "vulnerabilities", "vuln-1")]);
  });

  it("moves a hidden selection to the collapsed ancestor", () => {
    const state = collapse(loadedState(), domainNodeId(2));
    expect(visibleAncestor(state, branchNodeId(2, "foundations"))).toBe(domainNodeId(2));
    expect(visibleRows(visibleTree(state)).map((row) => row.id)).toEqual(["root", domainNodeId(2), domainNodeId(5)]);
  });

  it("lays out 1,000 visible topics quickly", () => {
    const branchId = branchNodeId(2, "vulnerabilities");
    let state = expand(loadedState(), [branchId]);
    for (let offset = 0; offset < 1000; offset += 50) state = applyTopicPage(state, branchId, { items: Array.from({ length: 50 }, (_, index) => vulnerability(offset + index)), total: 1000, offset, limit: 50 });
    const started = performance.now();
    const layout = layoutTree(visibleTree(state));
    const elapsed = performance.now() - started;
    console.info(`Laying out ${layout.positions.length} visible nodes took ${elapsed.toFixed(1)} ms`);
    expect(layout.positions.length).toBe(1005);
    expect(elapsed).toBeLessThan(500);
  });
});
