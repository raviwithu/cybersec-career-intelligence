import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SidebarNavigation from "../src/SidebarNavigation";

function renderSidebar(view = "dashboard", mobileOpen = false) {
  return render(<SidebarNavigation view={view} mobileOpen={mobileOpen} onNavigate={vi.fn()} onClose={vi.fn()} />);
}

beforeEach(() => {
  sessionStorage.clear();
  window.location.hash = "";
});

afterEach(() => {
  sessionStorage.clear();
  window.location.hash = "";
});

describe("grouped sidebar navigation", () => {
  it("keeps Explore and Administration collapsed or hidden by default", () => {
    renderSidebar();
    expect(screen.getByRole("button", { name: "Explore" }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("button", { name: "Domain Explorer" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Administration" })).toBeNull();
  });

  it("expands and collapses groups independently", () => {
    renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: "Explore" }));
    expect(screen.getByRole("button", { name: "Domain Explorer" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Career Development" }));
    expect(screen.getByRole("button", { name: "Career Readiness" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Explore" }));
    expect(screen.queryByRole("button", { name: "Domain Explorer" })).toBeNull();
    expect(screen.getByRole("button", { name: "Career Readiness" })).toBeTruthy();
  });

  it("auto-expands the active group and highlights the current page", () => {
    renderSidebar("readiness");
    expect(screen.getByRole("button", { name: "Career Development" }).getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("button", { name: "Career Readiness" }).getAttribute("aria-current")).toBe("page");
  });

  it("persists expanded groups across remounts", () => {
    const first = renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: "Explore" }));
    first.unmount();
    renderSidebar();
    expect(screen.getByRole("button", { name: "Domain Explorer" })).toBeTruthy();
  });

  it("shows Administration only after an administrator session is present", () => {
    sessionStorage.setItem("cybersec-career-intelligence.admin-api-key", "test-admin-key");
    renderSidebar("research-review");
    expect(screen.getByRole("button", { name: "Administration" }).getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("button", { name: "Research Review" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("button", { name: "Taxonomy Management" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Yahoo Job Alerts" })).toBeTruthy();
  });

  it("finds grouped pages through navigation search", () => {
    sessionStorage.setItem("cybersec-career-intelligence.admin-api-key", "test-admin-key");
    renderSidebar();
    fireEvent.change(screen.getByRole("textbox", { name: "Search navigation" }), { target: { value: "taxonomy" } });
    const result = screen.getByRole("option", { name: /Taxonomy Management/ });
    expect(result.textContent).toContain("Administration");
  });

  it("keeps nested pages reachable in collapsed mode through a flyout", () => {
    renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: "Collapse navigation" }));
    fireEvent.click(screen.getByRole("button", { name: "Explore" }));
    expect(screen.getByRole("menuitem", { name: "Domain Explorer" })).toBeTruthy();
  });

  it("closes the mobile drawer after navigation", () => {
    const onClose = vi.fn();
    const onNavigate = vi.fn();
    render(<SidebarNavigation view="dashboard" mobileOpen onNavigate={onNavigate} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Explore" }));
    fireEvent.click(screen.getByRole("button", { name: "Domain Explorer" }));
    expect(onNavigate).toHaveBeenCalledWith("domains");
    expect(onClose).toHaveBeenCalled();
  });

  it("resizes with the keyboard, clamps the width, and remembers it", () => {
    renderSidebar();
    const handle = screen.getByRole("separator", { name: "Resize navigation" });
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(handle.getAttribute("aria-valuenow")).toBe("268");
    expect(document.documentElement.style.getPropertyValue("--sidebar-width")).toBe("268px");
    expect(sessionStorage.getItem("cybersec-career-intelligence.sidebar-width")).toBe("268");
    fireEvent.keyDown(handle, { key: "End" });
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(handle.getAttribute("aria-valuenow")).toBe("440");
    fireEvent.doubleClick(handle);
    expect(handle.getAttribute("aria-valuenow")).toBe("252");
  });

  it("uses the collapsed width for the layout offset and hides the resize handle", () => {
    renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: "Collapse navigation" }));
    expect(screen.queryByRole("separator", { name: "Resize navigation" })).toBeNull();
    expect(document.documentElement.style.getPropertyValue("--sidebar-width")).toBe("76px");
  });
});
