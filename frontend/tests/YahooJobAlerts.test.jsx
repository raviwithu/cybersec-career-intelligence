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
    let countCalls = 0;
    let otherCalls = 0;
    let counts = { pending: 3, extraction_failed: 5, approval_blocked_no_description: 2, ingestion_fetching_description: 120, ingestion_queued: 40, ingestion_processing: 1, ingestion_analyzed: 85, ingestion_not_approved: 300 };
    global.fetch = vi.fn((url) => {
      if (url.includes("/job-candidates/counts")) { countCalls += 1; return response(counts); }
      if (url.includes("/job-candidates")) { listCalls += 1; return response({ items: [], total: 0, counts }); }
      otherCalls += 1;
      return response([]);
    });
    try {
      render(<YahooJobAlertsPage />);
      const bar = await screen.findByRole("region", { name: "Approval pipeline status" });
      expect(bar.textContent).toContain("161 job(s) in progress");
      expect(screen.getByRole("img", { name: "120 fetching descriptions, 40 queued for analysis, 1 analysing" })).toBeTruthy();
      expect(bar.textContent).toContain("Approval blocked: no description2");
      expect(bar.textContent).toContain("Analysed85");
      const listBefore = listCalls;
      const otherBefore = otherCalls;
      await vi.advanceTimersByTimeAsync(15000);
      await waitFor(() => expect(countCalls).toBe(1));
      // Unchanged counts: the candidate list is not refetched, and connections, sync runs and alert sources never are.
      expect(listCalls).toBe(listBefore);
      expect(otherCalls).toBe(otherBefore);
      counts = { ...counts, ingestion_fetching_description: 100, ingestion_queued: 60 };
      await vi.advanceTimersByTimeAsync(15000);
      await waitFor(() => expect(listCalls).toBe(listBefore + 1));
      expect(await screen.findByText(/161 job\(s\) in progress/)).toBeTruthy();
      expect(screen.getByRole("img", { name: "100 fetching descriptions, 60 queued for analysis, 1 analysing" })).toBeTruthy();
      expect(otherCalls).toBe(otherBefore);
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops polling and shows the error when the admin key is rejected", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let countCalls = 0;
    global.fetch = vi.fn((url) => {
      if (url.includes("/job-candidates/counts")) { countCalls += 1; return Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({ detail: "Administrator key rejected" }) }); }
      if (url.includes("/job-candidates")) return response({ items: [], total: 0, counts: { pending: 0, ingestion_queued: 2 } });
      return response([]);
    });
    try {
      render(<YahooJobAlertsPage />);
      await screen.findByRole("region", { name: "Approval pipeline status" });
      await vi.advanceTimersByTimeAsync(15000);
      expect(await screen.findByText(/Administrator key rejected/)).toBeTruthy();
      await vi.advanceTimersByTimeAsync(45000);
      expect(countCalls).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("refreshes untouched drawer fields from a poll but keeps the administrator's edits", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const job = { id: 1, title: "Detection Engineer", employer: "Example", location: "Remote", work_mode: "remote", job_url: "https://www.linkedin.com/jobs/view/1", source_provider: "LinkedIn Job Alerts", description_text: "Partial snippet", description_complete: false, description_status: "partial", review_status: "pending", duplicate_status: "unique", ingestion_status: "fetching_description", provenance: [], metadata: {} };
    let current = job;
    let counts = { pending: 1, ingestion_fetching_description: 1 };
    global.fetch = vi.fn((url) => {
      if (url.includes("/job-candidates/counts")) return response(counts);
      if (url.includes("/job-candidates/1")) return response(current);
      if (url.includes("/job-candidates")) return response({ items: [current], total: 1, counts });
      return response([]);
    });
    try {
      render(<YahooJobAlertsPage />);
      fireEvent.click(await screen.findByText("Detection Engineer"));
      const drawer = await screen.findByRole("dialog", { name: "Job candidate details" });
      const title = drawer.querySelector("input");
      fireEvent.change(title, { target: { value: "Senior Detection Engineer" } });
      current = { ...job, description_text: "Full description. ".repeat(30), description_complete: true, description_status: "complete", review_status: "approved", ingestion_status: "queued" };
      counts = { pending: 0, approved: 1, ingestion_queued: 1 };
      await vi.advanceTimersByTimeAsync(15000);
      await waitFor(() => expect(drawer.querySelector("textarea").value).toBe(current.description_text));
      expect(title.value).toBe("Senior Detection Engineer");
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not let a background poll discard a slow full refresh", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let listCalls = 0;
    let releaseConnections = null;
    const counts = { pending: 1, ingestion_fetching_description: 4 };
    global.fetch = vi.fn((url) => {
      if (url.includes("/job-candidates")) { listCalls += 1; return response({ items: [], total: 0, counts }); }
      if (url.includes("/connections") && releaseConnections === undefined) return new Promise((resolve) => { releaseConnections = () => resolve({ ok: true, status: 200, json: () => Promise.resolve([{ id: 1, messages_scanned: 4321, alerts_detected: 0, jobs_extracted: 0 }]) }); });
      return response([]);
    });
    try {
      render(<YahooJobAlertsPage />);
      await screen.findByRole("region", { name: "Approval pipeline status" });
      releaseConnections = undefined;
      fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
      await waitFor(() => expect(typeof releaseConnections).toBe("function"));
      const before = listCalls;
      await vi.advanceTimersByTimeAsync(15000);
      // The poll is skipped while the refresh is still loading.
      expect(listCalls).toBe(before);
      releaseConnections();
      expect(await screen.findByText("4321")).toBeTruthy();
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
