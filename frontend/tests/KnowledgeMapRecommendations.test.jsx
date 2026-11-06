import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import KnowledgeMapRecommendations from "../src/KnowledgeMapRecommendations";

const TOPIC = { topic_id: 31, topic_name: "Secure Boot", domain_id: 8, domain_name: "Boot Security", counts: { foundations: 2, security: 2, vulnerabilities: 3 }, rag_domain: "boot" };
const RAG = { id: "rag", label: "RAG knowledge DB", status: "connected", detail: "Private course material.", domains: [{ slug: "boot", name: "Boot", indexed: 38, indexed_pct: 36 }, { slug: "uefi", name: "UEFI", indexed: 20, indexed_pct: 100 }] };
const KIMI = { id: "kimi", label: "Kimi", model: "k3.1-pro", status: "connected", detail: "k3.1-pro through OpenWebUI." };
const BOTH = { id: "both", label: "RAG + Kimi", status: "connected", detail: "RAG drafts first, Kimi checks each draft." };
const EMPTY_TOPIC = { topic_id: 31, topic_name: "Wi-Fi Basics", domain_id: 9, domain_name: "Wireless", counts: { foundations: 0, security: 0, vulnerabilities: 0 }, rag_domain: null };
const UPDATE = { kind: "update_description", ref: "proposal:6152", expected_version: 2, branch: "foundations", name: "Boot Image Headers", current_description: "Old text.", description: "New text.", aliases: [], weak: false, sources: [] };
const ADDITION = { kind: "add_topic", ref: null, expected_version: null, branch: "vulnerabilities", name: "Fresh Weakness", current_description: null, description: "Something new.", aliases: [], weak: true, sources: [{ title: "Lesson 4.mp4", locator: "1 min 15 s", document_identifier: "videorag:transcript:12", content_hash: null }] };

const json = (body, status = 200) => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });

let posted;
let sources;
let topics;
let submitResult;
let reply;

beforeEach(() => {
  posted = [];
  sources = [RAG, KIMI, BOTH];
  reply = [UPDATE, ADDITION];
  topics = [TOPIC];
  submitResult = { proposals: [{ id: 6200 }], done: [0], errors: [] };
  global.fetch = vi.fn((url, options = {}) => {
    const path = new URL(url).pathname.replace("/api/v1", "");
    if (path === "/knowledge/admin/branch-recommendations") return json({ sources, topics });
    if (path === "/knowledge/admin/topics/31/branch-recommendations") { posted.push({ path, ...JSON.parse(options.body) }); return json({ topic_id: 31, source: "kimi", source_label: "Kimi (k3.1-pro)", recommendations: reply, warnings: ["Overlap was dropped."] }); }
    if (path === "/knowledge/admin/topics/31/branch-recommendations/submit") { posted.push({ path, ...JSON.parse(options.body) }); return json(submitResult); }
    throw new Error(`Unexpected request ${url}`);
  });
});

afterEach(() => { vi.restoreAllMocks(); });

const open = async () => {
  render(<KnowledgeMapRecommendations adminKey="key" />);
  fireEvent.change(await screen.findByLabelText("Topic"), { target: { value: "8:31" } });
};

describe("branch recommendations", () => {
  it("lists topics and offers every source with its status", async () => {
    await open();
    expect(screen.getByRole("option", { name: "Boot Security › Secure Boot (2 / 2 / 3)" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: /RAG knowledge DB/ })).toBeTruthy();
    expect(screen.getByRole("radio", { name: /^Kimi/ })).toBeTruthy();
    expect(screen.getByRole("radio", { name: /RAG \+ Kimi/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Get recommendations" }).disabled).toBe(true);
  });

  it("offers a topic whose branches are all empty", async () => {
    topics = [EMPTY_TOPIC];
    render(<KnowledgeMapRecommendations adminKey="key" />);
    expect(await screen.findByRole("option", { name: "Wireless › Wi-Fi Basics (0 / 0 / 0)" })).toBeTruthy();
  });

  it("says so when no topic can have branches", async () => {
    topics = [];
    render(<KnowledgeMapRecommendations adminKey="key" />);
    expect(await screen.findByText("No published topic sits directly under a domain yet.")).toBeTruthy();
  });

  it("disables a source that is not connected and shows why", async () => {
    sources = [{ ...RAG, status: "unavailable", detail: "The RAG knowledge DB could not be reached", domains: [] }, KIMI, BOTH];
    await open();
    expect(screen.getByRole("radio", { name: /RAG knowledge DB/ }).disabled).toBe(true);
    expect(screen.getByText("The RAG knowledge DB could not be reached")).toBeTruthy();
  });

  it("asks RAG with the suggested domain, which can be changed", async () => {
    await open();
    fireEvent.click(screen.getByRole("radio", { name: /RAG knowledge DB/ }));
    expect(screen.getByLabelText("RAG domain").value).toBe("boot");
    fireEvent.change(screen.getByLabelText("RAG domain"), { target: { value: "uefi" } });
    fireEvent.click(screen.getByRole("button", { name: "Get recommendations" }));
    await screen.findByText("Boot Image Headers");
    expect(posted[0]).toMatchObject({ domain_id: 8, source: "rag", rag_domain: "uefi" });
  });

  it("sends RAG + Kimi with the RAG domain and shows what Kimi made of each item", async () => {
    reply = [{ ...UPDATE, verification: "corrected", verification_note: "The first sentence overstated it." }, { ...ADDITION, verification: "confirmed" }, { ...ADDITION, name: "Gap Filler", sources: [], weak: false, verification: "kimi_only" }];
    await open();
    fireEvent.click(screen.getByRole("radio", { name: /RAG \+ Kimi/ }));
    expect(screen.getByLabelText("RAG domain").value).toBe("boot");
    fireEvent.click(screen.getByRole("button", { name: "Get recommendations" }));
    await screen.findByText("Boot Image Headers");
    expect(posted[0]).toMatchObject({ domain_id: 8, source: "both", rag_domain: "boot" });
    expect(screen.getByText("Kimi corrected")).toBeTruthy();
    expect(screen.getByText("Kimi confirmed")).toBeTruthy();
    expect(screen.getByText("Kimi only, no RAG source")).toBeTruthy();
    expect(screen.getByText("Kimi: The first sentence overstated it.")).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Update description: Boot Image Headers" }));
    fireEvent.click(screen.getByRole("button", { name: "Send 1 selected to review" }));
    await screen.findByRole("status");
    expect(posted.find((item) => item.path.endsWith("/submit")).items[0]).toMatchObject({ verification: "corrected", verification_note: "The first sentence overstated it." });
  });

  it("searches all RAG domains when the topic has no matching one", async () => {
    topics = [{ ...TOPIC, rag_domain: null }];
    await open();
    fireEvent.click(screen.getByRole("radio", { name: /RAG \+ Kimi/ }));
    expect(screen.getByLabelText("RAG domain").value).toBe("");
    expect(screen.getByRole("option", { name: "All domains" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Get recommendations" }));
    await screen.findByText("Boot Image Headers");
    expect(posted[0].source).toBe("both");
    expect(posted[0].rag_domain).toBeUndefined();
  });

  it("does not offer a RAG domain for RAG + Kimi when RAG is down", async () => {
    sources = [{ ...RAG, status: "unavailable", domains: [] }, KIMI, { ...BOTH, detail: "RAG is not available, so this would use Kimi alone." }];
    await open();
    fireEvent.click(screen.getByRole("radio", { name: /RAG \+ Kimi/ }));
    expect(screen.queryByLabelText("RAG domain")).toBeNull();
    expect(screen.getByRole("button", { name: "Get recommendations" }).disabled).toBe(false);
  });

  it("does not send a RAG domain to Kimi", async () => {
    await open();
    fireEvent.click(screen.getByRole("radio", { name: /^Kimi/ }));
    fireEvent.click(screen.getByRole("button", { name: "Get recommendations" }));
    await screen.findByText("Boot Image Headers");
    expect(posted[0].source).toBe("kimi");
    expect(posted[0].rag_domain).toBeUndefined();
  });

  it("shows old and new text, weak evidence and sources, and sends only what is selected", async () => {
    await open();
    fireEvent.click(screen.getByRole("radio", { name: /^Kimi/ }));
    fireEvent.click(screen.getByRole("button", { name: "Get recommendations" }));
    await screen.findByText("Boot Image Headers");
    expect(screen.getByText("Old text.")).toBeTruthy();
    expect(screen.getByText("New text.")).toBeTruthy();
    expect(screen.getByText("Weak evidence")).toBeTruthy();
    expect(screen.getByText(/Lesson 4\.mp4 \(1 min 15 s\)/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /selected to review/ }).disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Update description: Boot Image Headers" }));
    fireEvent.click(screen.getByRole("button", { name: "Send 1 selected to review" }));
    expect((await screen.findByRole("status")).textContent).toContain("1 proposal sent to review (#6200)");
    const sent = posted.find((item) => item.path.endsWith("/submit"));
    expect(sent.items).toHaveLength(1);
    expect(sent.items[0]).toMatchObject({ ref: "proposal:6152", expected_version: 2 });
    // Sent items leave the list, and the one not selected stays.
    await waitFor(() => expect(screen.queryByText("Boot Image Headers")).toBeNull());
    expect(screen.getByText("Fresh Weakness")).toBeTruthy();
  });

  it("keeps a refused item in the list and says why", async () => {
    submitResult = { proposals: [], done: [], errors: ["Boot Image Headers: Proposal changed; reload it before reviewing"] };
    await open();
    fireEvent.click(screen.getByRole("radio", { name: /^Kimi/ }));
    fireEvent.click(screen.getByRole("button", { name: "Get recommendations" }));
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select Update description: Boot Image Headers" }));
    fireEvent.click(screen.getByRole("button", { name: "Send 1 selected to review" }));
    expect((await screen.findByRole("status")).textContent).toContain("Proposal changed");
    expect(screen.getByText("Boot Image Headers")).toBeTruthy();
  });
});
