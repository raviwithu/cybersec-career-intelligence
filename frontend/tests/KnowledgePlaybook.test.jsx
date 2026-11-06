import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SectionContent } from "../src/KnowledgeSections";
import KnowledgeMapPage from "../src/KnowledgeMapPage";
import { applyDomainChildren, applyRoot, applyTopicChildren, domainNodeId, expand, facetNodeId, groupOfSection, initialMapState, layoutTree, opensTopicPanel, sectionGroupNodeId, topicNodeId, visibleTree } from "../src/knowledgeMapModel";

vi.mock("../src/KnowledgeMapGraph", () => ({ default: () => <div data-testid="graph-stub" /> }));

const web = { node_type: "domain", id: 1, slug: "web", name: "Web Application Security", child_domain_count: 0, placed_topic_count: 2 };
const topic = (id, key, name) => ({ node_type: "topic", domain_id: 1, id, topic_key: key, name, short_description: "", placement_count: 1, has_children: false });
const sqli = topic(7, "sqli", "SQL Injection");
const xss = topic(8, "xss", "Cross-Site Scripting");
const children = (topicId, sections) => ({ topic_id: topicId, domain_id: 1, sections, branches: [
  { branch: "foundations", label: "Foundations", topic_count: 0, items: [] },
  { branch: "security", label: "Security", topic_count: 0, items: [] },
  { branch: "vulnerabilities", label: "Common Vulnerabilities", topic_count: 0, items: [] },
] });
const placed = (key) => (key === "sqli" ? [{ domain_path: [{ id: 1, name: "Web Application Security" }], branch: null, label: null, ancestors: [] }] : []);

const CODE = { items: [
  { title: "Python lookup", language: "python", vulnerable: "execute(f'{status}')", secure: "execute('?', (status,))", explanation: "", security_control: "" },
  { title: "Java lookup", language: "java", vulnerable: "createStatement()", secure: "prepareStatement()", explanation: "", security_control: "" },
] };
const SOURCE = { entry_points: ["Query strings"], dangerous_sinks: ["Concatenated queries"], search_patterns: [{ language: "Python", pattern: 'execute(f"' }], easy_to_miss: ["ORDER BY"] };
const DYNAMIC = { steps: [{ title: "Compare responses", action: "Change the input.", look_for: "Differences." }], evidence: ["Request pairs"] };
const GATHER = { issue_checks: [{ what: "Entry points", how: "API spec", tells: "Which inputs to test." }], mitigation_checks: [{ what: "Prepared statements", how: "Database log", tells: "Whether binding happens." }] };
const CICD = {
  skill_id: "sqli-source-review", summary: "Scans changed code.", inputs: ["The diff"], outputs: ["SARIF report"], gate_policy: ["A person confirms each block"],
  pipelines: [{ system: "GitHub Actions", file_name: "scan.yml", content: "on: pull_request" }, { system: "GitLab CI", file_name: ".gitlab-ci.yml", content: "stage: test" }],
  example_finding: { location: "orders.py:4", explanation: "Input reaches the query.", suggested_fix: "Bind the value." },
};
const AI_DYNAMIC = {
  skill_id: "sqli-dynamic-analysis", summary: "Changes with your access.", guardrails: ["Authorised targets only"],
  access_levels: [
    { access: "binary", needs: ["The build"], steps: ["Trace database calls"], can_prove: ["Query text is assembled at runtime"], cannot_see: ["Paths never reached"] },
    { access: "remote", needs: ["Written permission"], steps: ["Compare responses"], can_prove: ["Behaviour changes"], cannot_see: ["The cause"] },
  ],
};
const section = (type, content) => ({ section_type: type, status: "published", published_version: 1, content });
const detail = { id: 7, topic_key: "sqli", name: "SQL Injection", description: "", sections: [section("overview", { short_description: "Input becomes SQL." }), section("code_examples", CODE), section("source_review", SOURCE), section("dynamic_review", DYNAMIC), section("attack_surfaces", { items: [{ name: "Query parameters", weakness_description: "Input reaches the query." }] }), section("references", { items: [{ title: "CWE-89", url: "https://cwe.mitre.org/data/definitions/89.html" }] })], related_topics: [], level_expectations: [], coverage: { items: [] } };

function mockApi() {
  global.fetch = vi.fn((url) => {
    const path = new URL(url).pathname.replace("/api/v1", "");
    const body = path === "/knowledge-map" ? { root: { id: "root", name: "CyberSec Career Intelligence" }, domains: [web] }
      : path === "/knowledge-map/domains/1/children" ? { domain: web, nodes: [sqli, xss] }
        : path === "/knowledge-map/domains/1/topics/7/children" ? children(7, ["overview", "attack_surfaces", "code_examples", "source_review", "dynamic_review", "references"])
          : path === "/knowledge-map/domains/1/topics/8/children" ? children(8, [])
            : path.endsWith("/placements") ? placed(path.split("/")[3])
              : path === "/knowledge/topics/sqli" ? detail
                : path === "/knowledge/topics/xss" ? { ...detail, id: 8, topic_key: "xss", name: "Cross-Site Scripting", sections: [] } : null;
    if (body === null) return Promise.reject(new Error(`Unexpected request ${url}`));
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
}

const findItem = (name) => screen.findByRole("treeitem", { name: new RegExp(`^${name}`) });
const press = (element, key) => fireEvent.keyDown(element, { key });
const row = (element) => element.querySelector(".km-tree-row");

async function openPlaybook() {
  render(<KnowledgeMapPage />);
  press(await findItem("Web Application Security"), "ArrowRight");
  press(await findItem("SQL Injection"), "ArrowRight");
  const playbook = await findItem("Playbook");
  press(playbook, "ArrowRight");
  return playbook;
}

beforeEach(() => {
  localStorage.setItem("cybersec-career-intelligence.knowledge-map-view", "list");
  window.location.hash = "#knowledge-map";
  mockApi();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  window.location.hash = "";
});

describe("section group model", () => {
  function loaded(sections) {
    let state = applyRoot(initialMapState(), { root: { name: "Root" }, domains: [web] });
    state = applyDomainChildren(state, domainNodeId(1), { nodes: [sqli] });
    return applyTopicChildren(state, topicNodeId(1, "sqli"), children(7, sections));
  }

  it("adds Learn, Playbook and Reference after the three branches, each with its sections in order", () => {
    const state = loaded(["references", "ai_cicd_skill", "code_examples", "overview", "career_levels"]);
    const ids = state.children[topicNodeId(1, "sqli")];
    expect(ids.map((id) => state.nodes[id].type)).toEqual(["branch", "branch", "branch", "section-group", "section-group", "section-group"]);
    expect(ids.slice(3).map((id) => state.nodes[id].label)).toEqual(["Learn", "Playbook", "Reference"]);
    expect(state.children[sectionGroupNodeId(1, "sqli", "playbook")]).toEqual([facetNodeId(1, "sqli", "code_examples"), facetNodeId(1, "sqli", "ai_cicd_skill")]);
    expect(state.children[sectionGroupNodeId(1, "sqli", "reference")].map((id) => state.nodes[id].label)).toEqual(["Career Levels", "References"]);
    expect(opensTopicPanel(state.nodes[facetNodeId(1, "sqli", "overview")])).toBe(true);
    expect(opensTopicPanel(state.nodes[sectionGroupNodeId(1, "sqli", "learn")])).toBe(false);
  });

  it("adds only the groups that have content, and ignores unknown sections", () => {
    const state = loaded(["overview", "future_section"]);
    expect(state.nodes[sectionGroupNodeId(1, "sqli", "learn")].sectionCount).toBe(1);
    expect(state.nodes[sectionGroupNodeId(1, "sqli", "playbook")]).toBeUndefined();
    expect(loaded([]).children[topicNodeId(1, "sqli")]).toHaveLength(3);
    expect(groupOfSection("future_section")).toBeNull();
  });

  it("gives a topic with no branches only its section groups", () => {
    const state = applyTopicChildren(loaded([]), topicNodeId(1, "sqli"), { topic_id: 7, domain_id: 1, branches: [], sections: ["overview", "mitigations"] });
    const kids = state.children[topicNodeId(1, "sqli")].map((id) => state.nodes[id]);
    expect(kids.map((node) => [node.type, node.label])).toEqual([["section-group", "Learn"], ["section-group", "Playbook"]]);
  });

  it("says so when a topic has no branches and no sections, so it does not expand to nothing", () => {
    const state = applyTopicChildren(loaded([]), topicNodeId(1, "sqli"), { topic_id: 7, domain_id: 1, branches: [], sections: [] });
    const kids = state.children[topicNodeId(1, "sqli")].map((id) => state.nodes[id]);
    expect(kids.map((node) => [node.type, node.label])).toEqual([["empty", "No published sections yet"]]);
  });

  it("lays every section out as a graph node when its group is open", () => {
    const sections = ["overview", "how_it_works", "attack_surfaces", "architecture", "real_world_examples", "code_examples", "mitigations", "source_review", "dynamic_review", "information_gathering", "ai_cicd_skill", "ai_dynamic_skill", "career_levels", "related", "references"];
    const topicId = topicNodeId(1, "sqli");
    const state = expand(loaded(sections), [domainNodeId(1), topicId, ...["learn", "playbook", "reference"].map((group) => sectionGroupNodeId(1, "sqli", group))]);
    const { positions, edges } = layoutTree(visibleTree(state));
    const facets = positions.filter((item) => item.node.type === "facet");
    expect(facets.map((item) => item.node.section).sort()).toEqual([...sections].sort());
    expect(edges.filter((edge) => edge.target.startsWith("facet:"))).toHaveLength(sections.length);
  });
});

describe("playbook on the map", () => {
  it("shows section groups only on topics that have content", async () => {
    render(<KnowledgeMapPage />);
    press(await findItem("Web Application Security"), "ArrowRight");
    const other = await findItem("Cross-Site Scripting");
    press(other, "ArrowRight");
    await within(other).findAllByRole("treeitem", { name: /^Foundations/ });
    expect(within(other).queryByRole("treeitem", { name: /^Playbook/ })).toBeNull();
  });

  it("opens the topic panel on a facet's section and writes the deep link", async () => {
    await openPlaybook();
    fireEvent.click(row(await findItem("Source Review")));
    const tab = await screen.findByRole("tab", { name: "Source Review" });
    await waitFor(() => expect(tab.getAttribute("aria-selected")).toBe("true"));
    expect(screen.getByRole("heading", { name: "SQL Injection" })).toBeTruthy();
    expect(screen.getByText("Concatenated queries")).toBeTruthy();
    expect(document.querySelector(".km-workspace").className).toContain("topic-open");
    expect(window.location.hash).toBe("#knowledge-map?topic=sqli&section=source_review");
  });

  it("moves the map selection when a panel tab is chosen", async () => {
    await openPlaybook();
    fireEvent.click(row(await findItem("Source Review")));
    fireEvent.click(await screen.findByRole("tab", { name: "Dynamic Review" }));
    await waitFor(() => expect(screen.getByRole("treeitem", { name: /^Dynamic Review/ }).getAttribute("aria-selected")).toBe("true"));
    // Learn is closed, so a tab from that group selects the topic instead of a hidden node.
    fireEvent.click(screen.getByRole("tab", { name: "Overview" }));
    await waitFor(() => expect(screen.getByRole("treeitem", { name: /^SQL Injection/ }).getAttribute("aria-selected")).toBe("true"));
    expect(screen.getByText("Input becomes SQL.")).toBeTruthy();
  });

  it("lists the sections when the Playbook node is selected, and each one opens its tab", async () => {
    const playbook = await openPlaybook();
    fireEvent.click(row(playbook));
    const details = screen.getByRole("complementary", { name: "Selected node details" });
    expect(await within(details).findByText("3 published sections. Select one to open it in the topic panel.")).toBeTruthy();
    expect(document.querySelector(".km-workspace").className).not.toContain("topic-open");
    fireEvent.click(within(details).getByRole("button", { name: "Dynamic Review" }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "Dynamic Review" }).getAttribute("aria-selected")).toBe("true"));
  });

  it("opens Learn and Reference sections from their nodes too", async () => {
    await openPlaybook();
    press(await findItem("Learn"), "ArrowRight");
    fireEvent.click(row(await findItem("Attack Surface")));
    await waitFor(() => expect(screen.getByRole("tab", { name: "Attack Surface" }).getAttribute("aria-selected")).toBe("true"));
    expect(await screen.findByText("Input reaches the query.")).toBeTruthy();
    press(await findItem("Reference"), "ArrowRight");
    fireEvent.click(row(await findItem("References")));
    await waitFor(() => expect(screen.getByRole("tab", { name: "References" }).getAttribute("aria-selected")).toBe("true"));
    expect(window.location.hash).toBe("#knowledge-map?topic=sqli&section=references");
  });

  it("opens the right group from a deep link to a Learn section", async () => {
    window.location.hash = "#knowledge-map?topic=sqli&section=attack_surfaces";
    render(<KnowledgeMapPage />);
    await waitFor(() => expect(screen.getByRole("treeitem", { name: /^Attack Surface/ }).getAttribute("aria-selected")).toBe("true"));
  });

  it("supports keyboard navigation through the facets", async () => {
    const playbook = await openPlaybook();
    await findItem("Example Code");
    press(playbook, "ArrowRight");
    press(document.activeElement, "ArrowDown");
    expect(document.activeElement.textContent).toContain("Source Review");
    expect(document.activeElement.getAttribute("aria-expanded")).toBeNull();
  });

  it("opens a section deep link, and a topic deep link still opens the topic", async () => {
    window.location.hash = "#knowledge-map?topic=sqli&section=dynamic_review";
    const first = render(<KnowledgeMapPage />);
    await waitFor(() => expect(screen.getByRole("treeitem", { name: /^Dynamic Review/ }).getAttribute("aria-selected")).toBe("true"));
    expect(await screen.findByText("Request pairs")).toBeTruthy();
    first.unmount();
    window.location.hash = "#knowledge-map?topic=sqli";
    render(<KnowledgeMapPage />);
    await waitFor(() => expect(screen.getByRole("treeitem", { name: /^SQL Injection/ }).getAttribute("aria-selected")).toBe("true"));
    expect(window.location.hash).toBe("#knowledge-map?topic=sqli");
  });

  it("falls back to the topic when a deep link names a section it does not have", async () => {
    window.location.hash = "#knowledge-map?topic=sqli&section=ai_cicd_skill";
    render(<KnowledgeMapPage />);
    await waitFor(() => expect(screen.getByRole("treeitem", { name: /^SQL Injection/ }).getAttribute("aria-selected")).toBe("true"));
  });
});

describe("playbook section content", () => {
  const show = (type, content) => render(<SectionContent section={section(type, content)} />);

  it("filters code examples by language, and shows no filter for one language", () => {
    show("code_examples", CODE);
    expect(screen.getByRole("heading", { name: "Python lookup" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Java lookup" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Java" }));
    expect(screen.getByRole("heading", { name: "Java lookup" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Python lookup" })).toBeNull();
  });

  it("does not offer a language filter for a single language", () => {
    show("code_examples", { items: CODE.items.slice(0, 1) });
    expect(screen.queryByRole("group", { name: "Language" })).toBeNull();
  });

  it("shows what mitigations do and do not cover", () => {
    show("mitigations", { items: [{ control: "Bind values", description: "Keeps values out of the SQL text.", control_type: "fixes", does_not_cover: "Column names." }] });
    expect(screen.getByText("Fixes the flaw")).toBeTruthy();
    expect(screen.getByText("Column names.")).toBeTruthy();
  });

  it("renders source review, dynamic review and information gathering", () => {
    show("source_review", SOURCE);
    expect(screen.getByText('execute(f"')).toBeTruthy();
    show("dynamic_review", DYNAMIC);
    expect(screen.getByText("Look for: Differences.")).toBeTruthy();
    show("information_gathering", GATHER);
    expect(screen.getByRole("heading", { name: "Is the mitigation in place?" })).toBeTruthy();
    expect(screen.getByText("Whether binding happens.")).toBeTruthy();
  });

  it("handles empty lists without blank headings", () => {
    show("source_review", {});
    show("information_gathering", {});
    expect(screen.queryByRole("heading")).toBeNull();
  });

  it("switches the pipeline file for the CI/CD skill", () => {
    show("ai_cicd_skill", CICD);
    expect(screen.getByText("scan.yml")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "GitLab CI" }));
    expect(screen.getByText(".gitlab-ci.yml")).toBeTruthy();
    expect(screen.getByText("orders.py:4")).toBeTruthy();
  });

  it("switches the dynamic skill by access level and always shows the guardrails", () => {
    show("ai_dynamic_skill", AI_DYNAMIC);
    expect(screen.getByText("Trace database calls")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Remote access only" }));
    expect(screen.getByText("Compare responses")).toBeTruthy();
    expect(screen.queryByText("Trace database calls")).toBeNull();
    expect(screen.getByText("Authorised targets only")).toBeTruthy();
  });

  it("shows a notice for a section that no longer validates", () => {
    show("dynamic_review", { content_hidden: true });
    expect(screen.getByRole("note").textContent).toContain("could not be displayed");
  });
});
