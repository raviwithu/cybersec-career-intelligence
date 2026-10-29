import { fireEvent, render, screen } from "@testing-library/react";
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
});
