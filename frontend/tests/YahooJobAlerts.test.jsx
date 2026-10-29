import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import YahooJobAlertsPage from "../src/YahooJobAlertsPage";

const response = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });

beforeEach(() => {
  sessionStorage.setItem("cybersec-career-intelligence.admin-api-key", "test-admin-key");
  global.fetch = vi.fn((url) => {
    if (url.includes("/job-candidates")) return response({ items: [], total: 0, counts: { pending: 0, approved: 0, rejected: 0, deferred: 0, duplicates: 0, extraction_failed: 0 } });
    if (url.includes("/connections")) return response([]);
    if (url.includes("/sync-runs")) return response([]);
    if (url.includes("/alert-sources")) return response([]);
    return response({});
  });
});

describe("Yahoo Job Alerts administrator page", () => {
  it("defaults to Job Inbox and exposes the four required tabs", async () => {
    render(<YahooJobAlertsPage />);
    expect(await screen.findByRole("heading", { name: "Job Inbox" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Job Inbox" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Mail Connection" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Alert Sources" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Sync History" })).toBeTruthy();
    expect(screen.getByText("jobalerts-noreply@linkedin.com")).toBeTruthy();
  });

  it("opens connection and history tabs without exposing credentials", async () => {
    render(<YahooJobAlertsPage />);
    await screen.findByRole("heading", { name: "Job Inbox" });
    fireEvent.click(screen.getByRole("tab", { name: "Mail Connection" }));
    expect(await screen.findByRole("heading", { name: "Yahoo Mail Connection" })).toBeTruthy();
    expect(screen.getByText(/imap\.mail\.yahoo\.com:993/)).toBeTruthy();
    expect(screen.queryByText(/encrypted_app_password|secret-app-password/)).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Sync History" }));
    expect(await screen.findByRole("heading", { name: "Sync History" })).toBeTruthy();
  });

  it("approves large selections in batches of 100 and summarises the result", async () => {
    const items = Array.from({ length: 250 }, (_, index) => ({ id: index + 1, title: `Job ${index + 1}`, employer: "Example", location: "Remote", source_provider: "LinkedIn Job Alerts", description_complete: false, review_status: "pending", duplicate_status: "unique", ingestion_status: "not_approved", first_seen_at: null }));
    const batches = [];
    global.fetch = vi.fn((url, options = {}) => {
      if (url.includes("/bulk-review")) {
        const ids = JSON.parse(options.body).candidate_ids;
        batches.push(ids.length);
        return response({ updated: ids.length - 1, approved: 0, fetching_description: ids.length - 1, skipped_duplicates: 1, skipped_already_approved: 0 });
      }
      if (url.includes("/job-candidates")) return response({ items, total: items.length, counts: { pending: items.length } });
      if (url.includes("/connections")) return response([]);
      return response([]);
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<YahooJobAlertsPage />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select all visible jobs" }));
    fireEvent.click(screen.getByRole("button", { name: "Approve 250" }));
    await waitFor(() => expect(batches).toEqual([100, 100, 50]));
    expect(await screen.findByText(/0 approved · 247 fetching full descriptions .* 3 duplicate\(s\) skipped\./)).toBeTruthy();
  });

  it("shows the approval pipeline status bar and polls while work is in progress", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let listCalls = 0;
    const counts = { pending: 3, extraction_failed: 2, ingestion_fetching_description: 120, ingestion_queued: 40, ingestion_processing: 1, ingestion_analyzed: 85, ingestion_not_approved: 300 };
    global.fetch = vi.fn((url) => {
      if (url.includes("/job-candidates")) { listCalls += 1; return response({ items: [], total: 0, counts }); }
      return response([]);
    });
    try {
      render(<YahooJobAlertsPage />);
      const bar = await screen.findByRole("region", { name: "Approval pipeline status" });
      expect(bar.textContent).toContain("161 job(s) in progress");
      expect(screen.getByRole("img", { name: "120 fetching descriptions, 40 queued for analysis, 1 analysing, 85 analysed" })).toBeTruthy();
      expect(bar.textContent).toContain("Description not found2");
      const before = listCalls;
      await vi.advanceTimersByTimeAsync(15000);
      await waitFor(() => expect(listCalls).toBeGreaterThan(before));
    } finally {
      vi.useRealTimers();
    }
  });

  it("hides the status bar when nothing has entered the pipeline", async () => {
    render(<YahooJobAlertsPage />);
    await screen.findByRole("heading", { name: "Job Inbox" });
    expect(screen.queryByRole("region", { name: "Approval pipeline status" })).toBeNull();
  });
});
