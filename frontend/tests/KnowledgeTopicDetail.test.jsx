import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import KnowledgeMapTopicPanel from "../src/KnowledgeMapTopicPanel";
import KnowledgeSectionEditor from "../src/KnowledgeSectionEditor";
import KnowledgeTopicPage from "../src/KnowledgeTopicPage";
import { isRenderableDiagram, layoutDiagram } from "../src/knowledgeDiagramLayout";
import { exploitationLabel } from "../src/KnowledgeSections";

// React Flow needs layout APIs jsdom lacks; the canvas is stubbed and its layout is tested as a pure function.
vi.mock("../src/KnowledgeDiagramCanvas", () => ({ default: ({ diagram, label }) => <div data-testid="diagram-canvas" aria-label={label}>{diagram.nodes.length} nodes, {diagram.edges.length} edges</div> }));

const LEVELS = [
  { id: 1, name: "Junior", slug: "junior", career_track: "shared", display_order: 1 },
  { id: 3, name: "Senior", slug: "senior", career_track: "shared", display_order: 3 },
  { id: 4, name: "Architect", slug: "architect", career_track: "technical", display_order: 4 },
  { id: 5, name: "Guide", slug: "guide", career_track: "management", display_order: 5 },
];

const DIAGRAM = {
  kind: "sequence", title: "Order lookup", variant: "vulnerable",
  nodes: [{ id: "user", label: "User", type: "actor", boundary: "internet" }, { id: "api", label: "Orders API", type: "service" }, { id: "db", label: "Orders DB", type: "datastore" }],
  edges: [{ from: "api", to: "db", label: "SELECT order 1002", order: 2 }, { from: "user", to: "api", label: "GET /orders/1002", order: 1 }],
  boundaries: [{ id: "internet", label: "Internet" }],
};

const section = (section_type, content) => ({ section_type, status: "published", published_version: 1, content, updated_at: "2026-01-01T00:00:00Z" });
const level = (id, name, expectation, practical) => ({ career_level: { id, name, slug: name.toLowerCase(), career_track: "shared" }, industry: null, expectation, practical_capability: practical });

function makeTopic(overrides = {}) {
  return {
    id: 1, topic_key: "idor", name: "IDOR / BOLA", slug: "idor", description: "Object-level authorization flaws.",
    sections: [section("overview", { short_description: "Accessing objects you do not own.", technical_explanation: "The server trusts a client-supplied identifier." })],
    coverage: { topic_id: 1, topic_key: "idor", complete: false, items: [] },
    related_topics: [], level_expectations: [], last_updated: null,
    ...overrides,
  };
}

function mockApi(topic) {
  global.fetch = vi.fn((url) => {
    const body = url.includes("/api/v1/levels") ? LEVELS : topic;
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
}

function renderPanel(topic, props = {}) {
  mockApi(topic);
  const node = { id: "topic:2:vulnerabilities:idor", type: "topic", label: topic.name, topicKey: topic.topic_key, placementCount: 1, description: "" };
  return render(<KnowledgeMapTopicPanel node={node} breadcrumb={["Root", "Cloud API Security", "Common Vulnerabilities", topic.name]} placements={{ loading: false, error: null, items: [] }} isCurrentPlacement={() => false} onReveal={() => {}} onSelectTopic={() => {}} {...props} />);
}

afterEach(() => vi.restoreAllMocks());

describe("Knowledge map topic panel", () => {
  it("shows only tabs that have published content", async () => {
    renderPanel(makeTopic({ sections: [section("overview", { short_description: "Accessing objects you do not own." }), section("mitigations", { items: [{ control: "Object-level authorization" }] })] }));
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["Overview", "Mitigations"]);
    expect(screen.queryByRole("tab", { name: "Real-World CVEs" })).toBeNull();
    expect(screen.queryByRole("tab", { name: "Career Levels" })).toBeNull();
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Mitigations" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("heading", { name: "Object-level authorization" })).toBeTruthy();
  });

  it("keeps the technical explanation behind Show technical details", async () => {
    renderPanel(makeTopic());
    expect(await screen.findByText("Accessing objects you do not own.")).toBeTruthy();
    expect(screen.queryByText("The server trusts a client-supplied identifier.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show technical details" }));
    expect(screen.getByText("The server trusts a client-supplied identifier.")).toBeTruthy();
  });

  it("renders code as text, never as HTML", async () => {
    const payload = "<img src=x onerror=alert(1)>";
    const { container } = renderPanel(makeTopic({ sections: [section("code_examples", { items: [{ title: "Reflected output", language: "javascript", vulnerable: `el.innerHTML = "${payload}";`, secure: `el.textContent = "${payload}";`, explanation: "Use textContent.", security_control: "Output encoding" }] })] }));
    fireEvent.click(await screen.findByRole("tab", { name: "Example Code" }));
    await waitFor(() => expect(container.querySelectorAll(".prism-code")).toHaveLength(2));
    expect(container.querySelector("img")).toBeNull();
    const panes = [...container.querySelectorAll(".kc-pane")];
    expect(panes[0].textContent).toContain(`el.innerHTML = "${payload}";`);
    expect(within(panes[0]).getByText("Vulnerable")).toBeTruthy();
    expect(within(panes[1]).getByText("Secure")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Copy vulnerable code for Reflected output" })).toBeTruthy();
    expect(screen.getByText("Output encoding")).toBeTruthy();
  });

  it("renders diagrams with a text alternative in edge order, and hides invalid ones with a notice", async () => {
    const broken = { ...DIAGRAM, title: "Broken", edges: [{ from: "user", to: "ghost" }] };
    renderPanel(makeTopic({ sections: [section("architecture", { diagrams: [DIAGRAM, broken] })] }));
    fireEvent.click(await screen.findByRole("tab", { name: "Architecture" }));
    expect(await screen.findByTestId("diagram-canvas")).toBeTruthy();
    expect(screen.getByTestId("diagram-canvas").textContent).toBe("3 nodes, 2 edges");
    const steps = within(screen.getByRole("list", { name: "Order lookup steps" })).getAllByRole("listitem").map((item) => item.textContent);
    expect(steps).toEqual(["User → Orders API: GET /orders/1002", "Orders API → Orders DB: SELECT order 1002"]);
    expect(screen.getByText(/Trust boundaries: Internet \(User\)/)).toBeTruthy();
    expect(screen.getByText("⚠ Vulnerable")).toBeTruthy();
    expect(screen.getAllByTestId("diagram-canvas")).toHaveLength(1);
    expect(screen.getByText("A diagram could not be displayed because the definition is invalid.")).toBeTruthy();
  });

  it("switches between vulnerable and secure flows in How It Works", async () => {
    renderPanel(makeTopic({ sections: [section("how_it_works", { workflow: "The client requests an order by id.", steps: ["Request", "Lookup"] }), section("architecture", { diagrams: [DIAGRAM, { ...DIAGRAM, title: "Scoped lookup", variant: "secure" }] })] }));
    fireEvent.click(await screen.findByRole("tab", { name: "How It Works" }));
    expect(screen.getByRole("list", { name: "Order lookup steps" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "✓ Secure" }));
    expect(screen.getByRole("list", { name: "Scoped lookup steps" })).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Order lookup steps" })).toBeNull();
  });

  it("switches career levels between Knowledge and Practical Skills, with an empty state", async () => {
    renderPanel(makeTopic({ level_expectations: [level(1, "Junior", "Explain object ownership checks.", "Find IDOR in a test app."), level(3, "Senior", "Design authorization models.", "Lead authorization reviews.")] }));
    fireEvent.click(await screen.findByRole("tab", { name: "Career Levels" }));
    const select = await screen.findByRole("combobox", { name: "Career level" });
    expect([...select.querySelectorAll("optgroup")].map((group) => group.label)).toEqual(["Shared", "Technical", "Management"]);
    expect(screen.getByRole("heading", { name: "Knowledge" })).toBeTruthy();
    expect(screen.getByText("Explain object ownership checks.")).toBeTruthy();
    expect(screen.getByText("Find IDOR in a test app.")).toBeTruthy();
    fireEvent.change(select, { target: { value: "3" } });
    expect(screen.getByText("Design authorization models.")).toBeTruthy();
    expect(screen.getByText("Lead authorization reviews.")).toBeTruthy();
    expect(screen.queryByText("Explain object ownership checks.")).toBeNull();
    fireEvent.change(select, { target: { value: "5" } });
    expect(screen.getByText("No expectations defined for this level yet.")).toBeTruthy();
    expect(screen.queryByText("Design authorization models.")).toBeNull();
  });

  it("shows legacy career guidance read-only when no level expectations exist", async () => {
    renderPanel(makeTopic({ sections: [section("career_level_guidance", { levels: { junior: "Know the basics.", guide: "" } })] }));
    fireEvent.click(await screen.findByRole("tab", { name: "Career Levels" }));
    expect(screen.getByText("Know the basics.")).toBeTruthy();
    expect(screen.getByText(/Legacy career guidance/)).toBeTruthy();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("labels exploitation conservatively and shows the CVE empty state", async () => {
    const items = [
      { cve_identifier: "CVE-2024-0001", affected_product: "Orders API", description: "Missing ownership check.", weakness: "CWE-639", impact: "Data exposure", exploitation_status: "exploited_in_the_wild", verification_status: "verified", reference: "https://example.com/advisory" },
      { cve_identifier: "CVE-2024-0002", exploitation_status: "exploited_in_the_wild", verification_status: "unverified", reference: "javascript:alert(1)" },
      { cve_identifier: "CVE-2024-0003", exploitation_status: "proof_of_concept", verification_status: "verified" },
    ];
    renderPanel(makeTopic({ sections: [section("real_world_examples", { items })] }));
    fireEvent.click(await screen.findByRole("tab", { name: "Real-World CVEs" }));
    const [first, second, third] = screen.getAllByRole("article");
    expect(within(first).getByText("Exploited in the wild")).toBeTruthy();
    expect(within(first).getByText("CWE-639")).toBeTruthy();
    const link = within(first).getByRole("link", { name: /Open reference/ });
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(within(second).queryByText("Exploited in the wild")).toBeNull();
    expect(within(second).getByText("Publicly disclosed")).toBeTruthy();
    expect(within(second).getByText("Unverified")).toBeTruthy();
    expect(within(second).queryByRole("link")).toBeNull();
    expect(within(third).getByText("Proof of concept")).toBeTruthy();
    expect(exploitationLabel({ exploitation_status: "exploited_in_the_wild", verification_status: "ai_derived" })).toBe("Publicly disclosed");
  });

  it("shows the empty CVE state when the section has no items", async () => {
    renderPanel(makeTopic({ sections: [section("real_world_examples", { items: [] })] }));
    fireEvent.click(await screen.findByRole("tab", { name: "Real-World CVEs" }));
    expect(screen.getByText("No verified real-world example has been added.")).toBeTruthy();
  });

  it("shows references with provenance and verification status", async () => {
    renderPanel(makeTopic({ sections: [section("references", { items: [{ title: "OWASP API Security Top 10", source_type: "standard", publisher: "OWASP", locator: "API1:2023", verification_status: "authoritative", url: "https://owasp.org/API-Security/" }] })] }));
    fireEvent.click(await screen.findByRole("tab", { name: "References" }));
    expect(screen.getByText("OWASP")).toBeTruthy();
    expect(screen.getByText("API1:2023")).toBeTruthy();
    expect(screen.getByText("Authoritative")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Open source/ }).getAttribute("href")).toBe("https://owasp.org/API-Security/");
  });

  it("links to the full Knowledge Base topic page", async () => {
    const onNavigate = vi.fn();
    renderPanel(makeTopic(), { onNavigate });
    fireEvent.click(await screen.findByRole("button", { name: "Open full topic page" }));
    expect(onNavigate).toHaveBeenCalledWith("knowledge-topic", "idor");
  });
});

describe("Knowledge Base topic page with shared renderers", () => {
  it("renders a How It Works diagram instead of raw JSON", async () => {
    mockApi([makeTopic({ sections: [section("how_it_works", { workflow: "Requests flow through the API.", diagram: DIAGRAM })] })]);
    render(<KnowledgeTopicPage />);
    expect(await screen.findByText("Requests flow through the API.")).toBeTruthy();
    expect(screen.getByTestId("diagram-canvas")).toBeTruthy();
    expect(screen.queryByText(/"nodes"/)).toBeNull();
  });

  it("treats the editor's empty default diagram as no diagram", async () => {
    mockApi([makeTopic({ sections: [section("how_it_works", { workflow: "No diagram yet.", diagram: { nodes: [], edges: [] } })] })]);
    render(<KnowledgeTopicPage />);
    expect(await screen.findByText("No diagram yet.")).toBeTruthy();
    expect(screen.queryByText(/could not be displayed/)).toBeNull();
  });
});

describe("diagram layout", () => {
  it("rejects diagrams with dangling edges or duplicate ids", () => {
    expect(isRenderableDiagram(DIAGRAM)).toBe(true);
    expect(isRenderableDiagram({ ...DIAGRAM, edges: [{ from: "user", to: "ghost" }] })).toBe(false);
    expect(isRenderableDiagram({ ...DIAGRAM, nodes: [...DIAGRAM.nodes, DIAGRAM.nodes[0]] })).toBe(false);
    expect(isRenderableDiagram({ nodes: [] })).toBe(false);
  });

  it("lays sequence diagrams out as lanes with one row per message", () => {
    const { nodes, edges } = layoutDiagram(DIAGRAM);
    const lanes = nodes.filter((node) => node.kind === "node");
    expect(lanes.map((node) => node.x)).toEqual([0, 210, 420]);
    expect(edges.map((edge) => edge.label)).toEqual(["1. GET /orders/1002", "2. SELECT order 1002"]);
    expect(nodes.filter((node) => node.kind === "lifeline")).toHaveLength(3);
  });

  it("keeps each trust boundary region around its own nodes only", () => {
    const diagram = { ...DIAGRAM, kind: "trust_boundary", nodes: [...DIAGRAM.nodes.map((node) => ({ ...node, boundary: node.id === "db" ? "internal" : node.boundary })), { id: "waf", label: "WAF", type: "control" }], boundaries: [{ id: "internet", label: "Internet" }, { id: "internal", label: "Internal" }], edges: [...DIAGRAM.edges, { from: "user", to: "waf" }] };
    const { nodes } = layoutDiagram(diagram);
    const regions = nodes.filter((node) => node.kind === "boundary");
    expect(regions.map((region) => region.label)).toEqual(["Internet", "Internal"]);
    const inside = (region, node) => node.x >= region.x && node.x <= region.x + region.width && node.y >= region.y && node.y <= region.y + region.height;
    nodes.filter((node) => node.kind === "node").forEach((node) => {
      regions.forEach((region) => expect(inside(region, node)).toBe(region.id === `boundary:${node.node.boundary}`));
    });
  });
});

describe("Knowledge section editor career levels", () => {
  it("builds career-level guidance keys from the active career levels", async () => {
    const levels = [...LEVELS, { id: 6, name: "Supervisor", slug: "supervisor", career_track: "management", display_order: 6 }];
    global.fetch = vi.fn((url) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(url.includes("/api/v1/levels") ? levels : { id: 1, name: "IDOR / BOLA", sections: [] }) }));
    render(<KnowledgeSectionEditor topic={{ id: 1, name: "IDOR / BOLA" }} adminKey="key" onClose={() => {}} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Section" }), { target: { value: "career_level_guidance" } });
    const editor = screen.getByRole("textbox", { name: /Structured section content/ });
    await waitFor(() => expect(JSON.parse(editor.value).levels).toEqual({ junior: "", senior: "", architect: "", guide: "", supervisor: "" }));
  });
});
