import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import KnowledgeTopicPage from "../src/KnowledgeTopicPage";

const topic = {
  id: 1,
  topic_key: "oauth-2",
  name: "OAuth 2.0",
  slug: "oauth-2",
  description: "Delegated authorization.",
  sections: [{ section_type: "overview", status: "published", published_version: 2, content: { short_description: "Delegated access without sharing credentials.", key_concepts: ["Authorization code"] }, updated_at: "2026-01-01T00:00:00Z" }, { section_type: "attack_surfaces", status: "published", published_version: 1, content: { items: [{ name: "Code interception", weakness_description: "The code is exposed." }] }, updated_at: "2026-01-01T00:00:00Z" }],
  coverage: { topic_id: 1, topic_key: "oauth-2", complete: false, items: [{ section_type: "overview", status: "published", published_version: 2 }, { section_type: "how_it_works", status: "missing", published_version: 0 }, { section_type: "attack_surfaces", status: "published", published_version: 1 }, { section_type: "mitigations", status: "missing", published_version: 0 }, { section_type: "real_world_examples", status: "missing", published_version: 0 }, { section_type: "references", status: "missing", published_version: 0 }] },
  related_topics: [],
};

afterEach(() => vi.restoreAllMocks());

describe("KnowledgeTopicPage", () => {
  it("renders published sections and missing coverage without drafts", async () => {
    global.fetch = vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([topic]) }));
    render(<KnowledgeTopicPage />);
    expect(await screen.findByRole("heading", { name: "OAuth 2.0" })).toBeTruthy();
    expect(screen.getByText("Mitigations not published")).toBeTruthy();
    expect(screen.queryByText(/draft/i)).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Attack Surfaces" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Code interception" })).toBeTruthy());
    expect(screen.getByText("The code is exposed.")).toBeTruthy();
  });
});
