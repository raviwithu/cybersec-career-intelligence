import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import KnowledgeMapPage from "../src/KnowledgeMapPage";
import SidebarNavigation, { getViewFromLocation } from "../src/SidebarNavigation";
import { applyDomainChildren, applyRoot, applyTopicChildren, branchNodeId, collapse, domainNodeId, expand, initialMapState, layoutTree, pathTo, topicNodeId, visibleAncestor, visibleRows, visibleTree } from "../src/knowledgeMapModel";

// React Flow needs real layout APIs that jsdom lacks; behaviour is tested through the list view and pure helpers.
vi.mock("../src/KnowledgeMapGraph", () => ({ default: () => <div data-testid="graph-stub" /> }));

const domain = (id, name, childCount = 0, topicCount = 0) => ({ node_type: "domain", id, slug: name.toLowerCase().replace(/ /g, "-"), name, child_domain_count: childCount, placed_topic_count: topicCount });
const topic = (id, key, name, placementCount = 1) => ({ id, topic_key: key, name, short_description: `${name} summary.`, placement_count: placementCount, has_children: false });
const inDomain = (domainId, item) => ({ node_type: "topic", domain_id: domainId, ...item });
// A topic's three branches, as GET /domains/{id}/topics/{topicId}/children returns them.
const branches = (topicId, domainId, { foundations = [], security = [], vulnerabilities = [] } = {}) => ({ topic_id: topicId, domain_id: domainId, branches: [
  { branch: "foundations", label: "Foundations", topic_count: foundations.length, items: foundations },
  { branch: "security", label: "Security", topic_count: security.length, items: security },
  { branch: "vulnerabilities", label: "Common Vulnerabilities", topic_count: vulnerabilities.length, items: vulnerabilities },
] });
const placement = (path, branch = null, label = null, ancestors = []) => ({ domain_path: path.map(([id, name]) => ({ id, name })), branch, label, ancestors });

const cloud = domain(2, "Cloud API Security", 0, 3);
const embedded = domain(5, "Embedded Systems Security", 1, 2);
const empty = domain(9, "Quantum Readiness", 0, 0);
const secureBoot = domain(6, "Secure Boot", 0, 1);
const oauth = { ...topic(1, "oauth-2", "OAuth 2.0", 2), has_children: true };
const apiAuthz = topic(2, "api-authz", "API Authorization");
const secureBootChain = topic(3, "secure-boot-chain", "Chain of Trust");
const pkce = { ...topic(11, "pkce", "PKCE"), has_children: true };
const idor = topic(400, "idor", "IDOR / BOLA");
const oauthPlacements = [placement([[2, "Cloud API Security"]]), placement([[5, "Embedded Systems Security"], [6, "Secure Boot"]])];
const oauthRef = { id: 1, topic_key: "oauth-2", name: "OAuth 2.0", branch: null };
const vulnerability = (index) => topic(1000 + index, `vuln-${index}`, `Vulnerability ${String(index).padStart(3, "0")}`);

function routes(url) {
  const { pathname, searchParams } = new URL(url);
  const path = pathname.replace("/api/v1", "");
  if (path === "/knowledge-map") return { root: { id: "root", name: "CyberSec Career Intelligence" }, domains: [cloud, embedded, empty] };
  if (path === "/knowledge-map/domains/2/children") return { domain: cloud, nodes: [inDomain(2, oauth), inDomain(2, apiAuthz)] };
  if (path === "/knowledge-map/domains/5/children") return { domain: embedded, nodes: [secureBoot, inDomain(5, secureBootChain)] };
  if (path === "/knowledge-map/domains/6/children") return { domain: secureBoot, nodes: [inDomain(6, oauth)] };
  if (path === "/knowledge-map/domains/9/children") return { domain: empty, nodes: [] };
  if (path === "/knowledge-map/domains/2/topics/1/children") return branches(1, 2, { foundations: [pkce], vulnerabilities: [idor, topic(401, "bola-graphql", "GraphQL BOLA")] });
  if (path === "/knowledge-map/domains/2/topics/11/children") return branches(11, 2, { foundations: [topic(12, "code-verifier", "Code Verifier")] });
  const children = path.match(/^\/knowledge-map\/domains\/(\d+)\/topics\/(\d+)\/children$/);
  if (children) return branches(Number(children[2]), Number(children[1]));
  if (path === "/knowledge-map/topics/oauth-2/placements") return oauthPlacements;
  if (path.startsWith("/knowledge-map/topics/")) return [];
  if (path === "/knowledge/topics/oauth-2") return { id: 1, topic_key: "oauth-2", name: "OAuth 2.0", description: "Delegated authorization." };
  if (path === "/knowledge-map/search") {
    const q = searchParams.get("q").toLowerCase();
    if (q.startsWith("idor")) return { query: q, items: [{ ...idor, short_description: "Object-level authorization flaws.", placements: [placement([[2, "Cloud API Security"]], "vulnerabilities", "Common Vulnerabilities", [oauthRef])] }] };
    if (q.startsWith("oauth")) return { query: q, items: [{ ...oauth, placements: oauthPlacements }] };
    if (q.startsWith("code")) return { query: q, items: [{ ...topic(12, "code-verifier", "Code Verifier"), placements: [placement([[2, "Cloud API Security"]], "foundations", "Foundations", [oauthRef, { id: 11, topic_key: "pkce", name: "PKCE", branch: "foundations" }])] }] };
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

  it("expands a domain into its sub-domains first, then its topics", async () => {
    const fetchMock = mockApi();
    const embeddedItem = (await renderMap(), item("Embedded Systems Security"));
    expect(requested(fetchMock, "/domains/5/children")).toBe(false);
    press(embeddedItem, "ArrowRight");
    await findItem("Chain of Trust");
    expect(embeddedItem.getAttribute("aria-expanded")).toBe("true");
    const children = within(groupOf(embeddedItem)).getAllByRole("treeitem").filter((element) => element.getAttribute("aria-level") === "3");
    expect(children.map((element) => element.textContent)).toEqual([expect.stringContaining("Secure Boot"), expect.stringContaining("Chain of Trust")]);
  });

  it("opens each topic, not the domain, into Foundations, Security and Common Vulnerabilities", async () => {
    const fetchMock = mockApi();
    await renderMap();
    press(item("Cloud API Security"), "ArrowRight");
    const oauthItem = await findItem("OAuth 2.0");
    const domainChildren = within(groupOf(item("Cloud API Security"))).getAllByRole("treeitem").filter((element) => element.getAttribute("aria-level") === "3");
    expect(domainChildren.map((element) => element.textContent)).toEqual([expect.stringContaining("OAuth 2.0"), expect.stringContaining("API Authorization")]);
    expect(oauthItem.getAttribute("aria-expanded")).toBe("false");
    press(oauthItem, "ArrowRight");
    await findItem("Foundations");
    const topicBranches = within(groupOf(oauthItem)).getAllByRole("treeitem").filter((element) => element.getAttribute("aria-level") === "4");
    expect(topicBranches.map((element) => element.textContent.replace(/\d+$/, "").replace(/^\W+/, ""))).toEqual(["Foundations", "Security", "Common Vulnerabilities"]);
    expect(requested(fetchMock, "/domains/2/topics/1/children")).toBe(true);
    // A branch's topics arrive with the topic, so opening a branch needs no request.
    const calls = fetchMock.mock.calls.length;
    press(within(groupOf(oauthItem)).getByRole("treeitem", { name: /^Common Vulnerabilities/ }), "ArrowRight");
    expect(await findItem("IDOR / BOLA")).toBeTruthy();
    expect(fetchMock.mock.calls.length).toBe(calls);
  });

  it("shows a placeholder for a domain without topics and for an empty branch", async () => {
    mockApi();
    await renderMap();
    press(item("Quantum Readiness"), "ArrowRight");
    expect(await findItem("No published topics yet")).toBeTruthy();
    press(item("Cloud API Security"), "ArrowRight");
    press(await findItem("API Authorization"), "ArrowRight");
    await waitFor(() => expect(within(groupOf(item("API Authorization"))).getAllByRole("treeitem", { name: /^(Foundations|Security|Common Vulnerabilities)/ })).toHaveLength(3));
    press(within(groupOf(item("API Authorization"))).getByRole("treeitem", { name: /^Security/ }), "ArrowRight");
    await waitFor(() => expect(screen.getAllByRole("treeitem", { name: /^No published topics yet/ })).toHaveLength(2));
  });

  it("selecting a topic opens the details panel and the breadcrumb", async () => {
    mockApi();
    await renderMap();
    press(item("Cloud API Security"), "ArrowRight");
    press(await findItem("OAuth 2.0"), "Enter");
    const details = screen.getByRole("complementary", { name: "Selected node details" });
    expect(within(details).getByRole("heading", { name: "OAuth 2.0" })).toBeTruthy();
    expect(await within(details).findByText("Delegated authorization.")).toBeTruthy();
    expect(await within(details).findByRole("button", { name: "Embedded Systems Security › Secure Boot" })).toBeTruthy();
    const crumbs = within(screen.getByRole("navigation", { name: "Selected path" })).getAllByRole("listitem").map((element) => element.textContent);
    expect(crumbs).toEqual(["CyberSec Career Intelligence", "Cloud API Security", "OAuth 2.0"]);
    expect(window.location.hash).toBe("#knowledge-map?topic=oauth-2");
    fireEvent.click(within(screen.getByRole("navigation", { name: "Selected path" })).getByRole("button", { name: "Cloud API Security" }));
    expect(within(details).getByRole("heading", { name: "Cloud API Security" })).toBeTruthy();
  });

  it("search reveals only the path to the result, through its parent topic's branch", async () => {
    const fetchMock = mockApi();
    await renderMap();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "idor" } });
    const result = await screen.findByRole("button", { name: /IDOR \/ BOLA/ });
    expect(result.textContent).toContain("Cloud API Security › OAuth 2.0 › Common Vulnerabilities");
    fireEvent.click(result);
    const idorItem = await findItem("IDOR / BOLA");
    expect(idorItem.getAttribute("aria-selected")).toBe("true");
    expect(item("Cloud API Security").getAttribute("aria-expanded")).toBe("true");
    expect(item("OAuth 2.0").getAttribute("aria-expanded")).toBe("true");
    expect(item("Common Vulnerabilities").getAttribute("aria-expanded")).toBe("true");
    expect(item("Foundations").getAttribute("aria-expanded")).toBe("false");
    expect(item("Embedded Systems Security").getAttribute("aria-expanded")).toBe("false");
    expect(requested(fetchMock, "/domains/5/children")).toBe(false);
  });

  it("asks which path to use when a search result has several placements", async () => {
    mockApi();
    await renderMap();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "oauth" } });
    fireEvent.click(await screen.findByRole("button", { name: /OAuth 2\.0.*2 locations/ }));
    fireEvent.click(within(screen.getByRole("group", { name: "Choose where to show OAuth 2.0" })).getByRole("button", { name: "Embedded Systems Security › Secure Boot" }));
    await waitFor(() => expect(item("OAuth 2.0").getAttribute("aria-selected")).toBe("true"));
    expect(item("Secure Boot").getAttribute("aria-expanded")).toBe("true");
    expect(item("Cloud API Security").getAttribute("aria-expanded")).toBe("false");
  });

  it("nests topics inside topics' branches, at any depth", async () => {
    mockApi();
    press(await renderMap(), "ArrowRight");
    const parent = await findItem("OAuth 2.0");
    press(parent, "ArrowRight");
    const foundations = await findItem("Foundations");
    press(foundations, "ArrowRight");
    const pkceItem = await findItem("PKCE");
    expect(pkceItem.getAttribute("aria-level")).toBe(String(Number(parent.getAttribute("aria-level")) + 2));
    press(pkceItem, "ArrowRight");
    await waitFor(() => expect(within(groupOf(pkceItem)).getAllByRole("treeitem", { name: /^(Foundations|Security|Common Vulnerabilities)/ })).toHaveLength(3));
    press(within(groupOf(pkceItem)).getByRole("treeitem", { name: /^Foundations/ }), "ArrowRight");
    expect((await findItem("Code Verifier")).getAttribute("aria-level")).toBe(String(Number(pkceItem.getAttribute("aria-level")) + 2));
  });

  it("search opens a nested topic under each of its parent topics", async () => {
    mockApi();
    await renderMap();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "code" } });
    const result = await screen.findByRole("button", { name: /Code Verifier/ });
    expect(result.textContent).toContain("Cloud API Security › OAuth 2.0 › Foundations › PKCE › Foundations");
    fireEvent.click(result);
    await waitFor(() => expect(item("Code Verifier").getAttribute("aria-selected")).toBe("true"));
    expect(item("OAuth 2.0").getAttribute("aria-expanded")).toBe("true");
    expect(item("PKCE").getAttribute("aria-expanded")).toBe("true");
    expect(screen.getAllByRole("treeitem", { name: /^Code Verifier/ })).toHaveLength(1);
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
      if (url.endsWith("/knowledge/topics/oauth-2")) return json({ id: 1, topic_key: "oauth-2", name: "OAuth 2.0", description: "Delegated authorization.", sections: [], level_expectations: [], related_topics: [{ id: 3, topic_key: "secure-boot-chain", name: "Chain of Trust", relationship_type: "dependency", direction: "incoming", label: "Used by" }] });
      if (url.endsWith("/knowledge/topics/secure-boot-chain")) return json({ id: 3, topic_key: "secure-boot-chain", name: "Chain of Trust", description: "", sections: [], level_expectations: [], related_topics: [] });
      if (url.endsWith("/knowledge-map/topics/secure-boot-chain/placements")) return json([placement([[5, "Embedded Systems Security"]])]);
      return null;
    });
    render(<KnowledgeMapPage />);
    const details = await screen.findByRole("complementary", { name: "Selected node details" });
    fireEvent.click(await within(details).findByRole("tab", { name: "Related Topics" }));
    expect(within(details).getByText("Used by")).toBeTruthy();
    fireEvent.click(within(details).getByRole("button", { name: "Chain of Trust" }));
    await waitFor(() => expect(item("Chain of Trust").getAttribute("aria-selected")).toBe("true"));
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
    await findItem("OAuth 2.0");
    press(document.activeElement, "ArrowRight");
    expect(document.activeElement).toBe(item("OAuth 2.0"));
    press(document.activeElement, "ArrowLeft");
    expect(document.activeElement).toBe(item("Cloud API Security"));
    press(document.activeElement, "ArrowLeft");
    expect(item("Cloud API Security").getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("treeitem", { name: /^OAuth/ })).toBeNull();
    expect(item("Cloud API Security").tabIndex).toBe(0);
  });

  it("collapse hides descendants and Go to parent selects the parent", async () => {
    mockApi();
    await renderMap();
    press(item("Cloud API Security"), "ArrowRight");
    press(await findItem("OAuth 2.0"), "ArrowRight");
    press(await findItem("Foundations"), "Enter");
    fireEvent.click(screen.getByRole("button", { name: "Go to parent" }));
    expect(item("OAuth 2.0").getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Go to parent" }));
    expect(item("Cloud API Security").getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Collapse" }));
    expect(screen.queryByRole("treeitem", { name: /^Foundations/ })).toBeNull();
    expect(screen.queryByRole("treeitem", { name: /^OAuth/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    expect(item("OAuth 2.0")).toBeTruthy();
    expect(item("Foundations")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Collapse all" }));
    expect(screen.queryByRole("treeitem", { name: /^OAuth/ })).toBeNull();
    expect(item("Cloud API Security").getAttribute("aria-selected")).toBe("true");
  });

  it("expand children opens one level below the selection", async () => {
    mockApi();
    await renderMap();
    fireEvent.click(screen.getByRole("button", { name: "Expand children" }));
    await findItem("Secure Boot");
    await waitFor(() => expect(within(groupOf(item("Cloud API Security"))).getByRole("treeitem", { name: /^OAuth 2\.0/ })).toBeTruthy());
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
    expect(await findItem("OAuth 2.0")).toBeTruthy();
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

  it("stays responsive with a 1,000-topic branch", async () => {
    const total = 1000;
    mockApi((url) => (url.endsWith("/domains/2/topics/1/children")
      ? Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(branches(1, 2, { vulnerabilities: Array.from({ length: total }, (_, index) => vulnerability(index)) })) })
      : null));
    // Role queries compute accessible names over every nested item, which is quadratic here; look rows up by label.
    const byLabel = (text) => [...document.querySelectorAll(".km-tree-label")].find((element) => element.textContent === text)?.closest("[role=treeitem]");
    await renderMap();
    press(item("Cloud API Security"), "ArrowRight");
    press(await findItem("OAuth 2.0"), "ArrowRight");
    const vulnerabilities = await waitFor(() => { const element = byLabel("Common Vulnerabilities"); if (!element) throw new Error("not loaded"); return element; });
    const opened = performance.now();
    press(vulnerabilities, "ArrowRight");
    const last = await waitFor(() => { const element = byLabel("Vulnerability 999"); if (!element) throw new Error("not loaded"); return element; });
    const openTime = performance.now() - opened;
    const started = performance.now();
    press(last, "Enter");
    expect(last.getAttribute("aria-selected")).toBe("true");
    const elapsed = performance.now() - started;
    console.info(`1,000 topics: opening the branch ${openTime.toFixed(0)} ms; selecting a topic ${elapsed.toFixed(1)} ms`);
    expect(elapsed).toBeLessThan(1000);
    expect(document.querySelectorAll(".km-tree-row.km-node-topic").length).toBe(total + 2);
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
  const oauthId = topicNodeId(2, "oauth-2");
  function loadedState(vulnerabilities = [vulnerability(0), vulnerability(1)]) {
    let state = applyRoot(initialMapState(), { root: { id: "root", name: "Root" }, domains: [cloud, embedded] });
    state = applyDomainChildren(state, domainNodeId(2), { nodes: [inDomain(2, oauth)] });
    state = applyTopicChildren(state, oauthId, branches(1, 2, { foundations: [pkce], vulnerabilities }));
    return expand(state, [domainNodeId(2), oauthId]);
  }

  it("lays the visible tree out left to right from structure alone", () => {
    const state = loadedState();
    const layout = layoutTree(visibleTree(state));
    const x = Object.fromEntries(layout.positions.map((position) => [position.id, position.x]));
    expect(x.root).toBeLessThan(x[domainNodeId(2)]);
    expect(x[domainNodeId(2)]).toBeLessThan(x[oauthId]);
    expect(x[oauthId]).toBeLessThan(x[branchNodeId(2, "oauth-2", "foundations")]);
    expect(layout.edges).toContainEqual(expect.objectContaining({ source: oauthId, target: branchNodeId(2, "oauth-2", "vulnerabilities") }));
    expect(layout.positions.map((position) => position.id)).not.toContain(domainNodeId(6));
  });

  it("puts a branch's topics under the branch, inside the topic and its domain", () => {
    const state = loadedState();
    const branchId = branchNodeId(2, "oauth-2", "foundations");
    expect(state.nodes[branchId]).toMatchObject({ type: "branch", parentTopicId: 1, parentTopicKey: "oauth-2", branch: "foundations", topicCount: 1 });
    expect(state.nodes[topicNodeId(2, "pkce")]).toMatchObject({ parentTopicId: 1, branch: "foundations", domainId: 2 });
    expect(pathTo(state, topicNodeId(2, "pkce"))).toEqual(["root", domainNodeId(2), oauthId, branchId, topicNodeId(2, "pkce")]);
    expect(state.children[branchNodeId(2, "oauth-2", "security")]).toEqual([`empty:${branchNodeId(2, "oauth-2", "security")}`]);
  });

  it("moves a hidden selection to the collapsed ancestor", () => {
    const state = collapse(loadedState(), domainNodeId(2));
    expect(visibleAncestor(state, branchNodeId(2, "oauth-2", "foundations"))).toBe(domainNodeId(2));
    expect(visibleRows(visibleTree(state)).map((row) => row.id)).toEqual(["root", domainNodeId(2), domainNodeId(5)]);
  });

  it("lays out 1,000 visible topics quickly", () => {
    const state = expand(loadedState(Array.from({ length: 1000 }, (_, index) => vulnerability(index))), [branchNodeId(2, "oauth-2", "vulnerabilities")]);
    const started = performance.now();
    const layout = layoutTree(visibleTree(state));
    const elapsed = performance.now() - started;
    console.info(`Laying out ${layout.positions.length} visible nodes took ${elapsed.toFixed(1)} ms`);
    expect(layout.positions.length).toBe(1007);
    expect(elapsed).toBeLessThan(500);
  });
});

describe("graph node styles", () => {
  it("keeps graph nodes clickable, because React Flow turns pointer events off on non-selectable nodes", () => {
    // The graph is stubbed in these tests and jsdom has no hit testing, so this guards the rule itself.
    const css = readFileSync(resolve(process.cwd(), "src/app.css"), "utf8");
    expect(css).toMatch(/\.km-graph \.km-node\s*\{\s*pointer-events:\s*all;/);
  });
});
