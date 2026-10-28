import { useEffect, useMemo, useState } from "react";

import { getAdminSessionKey } from "./api";

const GROUP_STATE_KEY = "cybersec-career-intelligence.navigation-groups";
const SIDEBAR_MODE_KEY = "cybersec-career-intelligence.sidebar-mode";

export const navigationGroups = [
  {
    id: "explore",
    label: "Explore",
    icon: "◈",
    items: [
      { id: "domains", label: "Domain Explorer", icon: "◈" },
      { id: "industry-intelligence", label: "Industry Explorer", icon: "◇" },
      { id: "competencies", label: "Competency Explorer", icon: "◎" },
      { id: "matrix", label: "Career Matrix", icon: "▦" },
      { id: "compare", label: "Career Comparison", icon: "⇄", group: "Comparisons" },
      { id: "industry-comparison", label: "Industry Comparison", icon: "⇄", group: "Comparisons" },
    ],
  },
  {
    id: "career",
    label: "Career Development",
    icon: "↗",
    items: [
      { id: "readiness", label: "Career Readiness", icon: "◎" },
      { id: "career-progression", label: "Career Progression", icon: "⇢" },
      { id: "skill-trends", label: "Skill Trends", icon: "↗" },
      { id: "competency-gaps", label: "Gap Analysis", icon: "△" },
      { id: "career-roadmap", label: "Career Roadmap", icon: "⌁" },
      { id: "profile", label: "My Profile", icon: "●" },
    ],
  },
  {
    id: "research-intelligence",
    label: "Research Intelligence",
    icon: "◉",
    items: [
      { id: "intelligence-dashboard", label: "Intelligence Dashboard", icon: "◉" },
      { id: "research-coverage", label: "Research Coverage", icon: "▥" },
      { id: "evidence-explorer", label: "Evidence Explorer", icon: "⌗" },
      { id: "ask-career", label: "Ask Career Intelligence", icon: "?" },
    ],
  },
  {
    id: "administration",
    label: "Administration",
    icon: "⌘",
    adminOnly: true,
    items: [
      { id: "research-ingestion", label: "Research Ingestion", icon: "↻" },
      { id: "research-review", label: "Research Review", icon: "✓" },
      { id: "career-readiness-review", label: "Career Readiness Review", icon: "◇" },
      { id: "knowledge-topics", label: "Knowledge Topic Management", icon: "☷" },
      { id: "taxonomy-management", label: "Taxonomy Management", icon: "⌘" },
      { id: "research", label: "AI Model Configuration", icon: "✦" },
      { id: "publication-history", label: "Publication History", icon: "▤" },
    ],
  },
];

const dashboard = { id: "dashboard", label: "Dashboard", icon: "⌂" };
const profileItem = { id: "profile", label: "My Profile", icon: "●" };
const legacyItems = {
  search: { id: "search", label: "Global Search", icon: "⌕" },
  "automated-research": { id: "automated-research", label: "Automated Research", icon: "↻" },
};

export const legacyViewIds = new Set(Object.keys(legacyItems));

function readSessionJson(key, fallback) {
  try {
    const value = window.sessionStorage.getItem(key);
    return value ? { ...fallback, ...JSON.parse(value) } : fallback;
  } catch {
    return fallback;
  }
}

function flattenItems(items) {
  return items.flatMap((item) => [item, ...(item.children || [])]);
}

export function findNavigationItem(view) {
  if (view === dashboard.id) return dashboard;
  if (view === profileItem.id) return profileItem;
  if (legacyItems[view]) return legacyItems[view];
  for (const group of navigationGroups) {
    const item = flattenItems(group.items).find((candidate) => candidate.id === view);
    if (item) return item;
  }
  return null;
}

export function getViewFromLocation() {
  if (typeof window === "undefined") return "dashboard";
  const view = window.location.hash.replace(/^#/, "");
  return view && (findNavigationItem(view) || view === "research-ingestion" || view === "publication-history" || view === "research-coverage") ? view : "dashboard";
}

function defaultGroupState() {
  return { explore: false, career: false, "research-intelligence": false, administration: false };
}

export default function SidebarNavigation({ view, onNavigate, mobileOpen, onClose }) {
  const [collapsed, setCollapsed] = useState(() => typeof window !== "undefined" && window.sessionStorage.getItem(SIDEBAR_MODE_KEY) === "collapsed");
  const [groups, setGroups] = useState(() => typeof window === "undefined" ? defaultGroupState() : readSessionJson(GROUP_STATE_KEY, defaultGroupState()));
  const [flyoutGroup, setFlyoutGroup] = useState(null);
  const [search, setSearch] = useState("");
  const [adminAuthorized, setAdminAuthorized] = useState(() => Boolean(getAdminSessionKey()));

  const activeGroup = navigationGroups.find((group) => group.items.some((item) => item.id === view));
  const visibleGroups = navigationGroups.filter((group) => !group.adminOnly || adminAuthorized);
  const searchResults = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return [];
    return visibleGroups.flatMap((group) => group.items.filter((item) => item.label.toLowerCase().includes(term)).map((item) => ({ ...item, groupLabel: group.label })));
  }, [search, visibleGroups]);

  useEffect(() => {
    if (activeGroup) {
      setGroups((current) => current[activeGroup.id] ? current : { ...current, [activeGroup.id]: true });
    }
  }, [activeGroup?.id]);

  useEffect(() => {
    const onAdminSessionChange = () => setAdminAuthorized(Boolean(getAdminSessionKey()));
    window.addEventListener("admin-session-changed", onAdminSessionChange);
    return () => window.removeEventListener("admin-session-changed", onAdminSessionChange);
  }, []);

  function persistGroups(next) {
    setGroups(next);
    window.sessionStorage.setItem(GROUP_STATE_KEY, JSON.stringify(next));
  }

  function toggleGroup(group) {
    if (collapsed) {
      setFlyoutGroup((current) => current === group.id ? null : group.id);
      return;
    }
    persistGroups({ ...groups, [group.id]: !groups[group.id] });
  }

  function navigate(item) {
    setFlyoutGroup(null);
    onNavigate(item.id);
    onClose();
  }

  function toggleCollapsed() {
    const next = !collapsed;
    setCollapsed(next);
    setFlyoutGroup(null);
    window.sessionStorage.setItem(SIDEBAR_MODE_KEY, next ? "collapsed" : "expanded");
  }

  function renderItem(item, nested = false) {
    const active = view === item.id;
    return <button type="button" key={`${item.id}-${item.label}`} className={`nav-item ${active ? "active" : ""} ${nested ? "nav-item-nested" : ""}`} aria-current={active ? "page" : undefined} title={collapsed ? item.label : undefined} onClick={() => navigate(item)}><span className="nav-icon" aria-hidden="true">{item.icon}</span><span className="nav-label">{item.label}</span></button>;
  }

  function renderGroup(group) {
    const expanded = groups[group.id];
    const isActive = activeGroup?.id === group.id;
    return <div className={`nav-group ${isActive ? "has-active" : ""}`} key={group.id}>
      <button type="button" className={`nav-group-toggle ${isActive ? "active" : ""}`} aria-expanded={collapsed ? flyoutGroup === group.id : Boolean(expanded)} aria-controls={`nav-group-${group.id}`} title={collapsed ? group.label : undefined} onClick={() => toggleGroup(group)}><span className="nav-icon" aria-hidden="true">{group.icon}</span><span className="nav-label">{group.label}</span><span className="nav-chevron" aria-hidden="true">{collapsed ? "›" : expanded ? "⌄" : "›"}</span></button>
      {collapsed && flyoutGroup === group.id && <div className="nav-flyout" id={`nav-group-${group.id}`} role="menu"><strong>{group.label}</strong>{group.items.map((item) => <button type="button" role="menuitem" className={view === item.id ? "active" : ""} key={`${group.id}-${item.id}-${item.label}`} onClick={() => navigate(item)}>{item.label}</button>)}</div>}
      {!collapsed && expanded && <div className="nav-group-items" id={`nav-group-${group.id}`}>{group.items.map((item) => <div className="nav-item-wrap" key={`${group.id}-${item.id}-${item.label}`}>{item.group && <span className="nav-subgroup-label">{item.group}</span>}{renderItem(item, Boolean(item.group))}</div>)}</div>}
    </div>;
  }

  return <>
    <aside className={`sidebar ${mobileOpen ? "open" : ""} ${collapsed ? "sidebar-collapsed" : ""}`} aria-label="Primary navigation">
      <div className="brand"><div className="brand-mark">C<span>·</span></div><div className="nav-label"><strong>CyberSec</strong><small>Career Intelligence</small></div></div>
      <div className="sidebar-toolbar"><span className="sidebar-label nav-label">WORKSPACE</span><button type="button" className="sidebar-mode-toggle" aria-label={collapsed ? "Expand navigation" : "Collapse navigation"} onClick={toggleCollapsed}>{collapsed ? "»" : "«"}</button></div>
      {!collapsed && <label className="navigation-search"><span aria-hidden="true">⌕</span><input aria-label="Search navigation" placeholder="Find a page" value={search} onChange={(event) => setSearch(event.target.value)} /></label>}
      {search && !collapsed && <div className="navigation-search-results" role="listbox" aria-label="Navigation search results">{searchResults.length ? searchResults.map((item) => <button type="button" role="option" key={`${item.groupLabel}-${item.id}-${item.label}`} onClick={() => { navigate(item); setSearch(""); }}><span>{item.label}</span><small>{item.groupLabel}</small></button>) : <span className="navigation-empty">No matching pages</span>}</div>}
      <nav className="sidebar-nav" aria-label="Workspace pages">
        {renderItem(dashboard)}
        {visibleGroups.map(renderGroup)}
      </nav>
      <div className="sidebar-footer">{renderItem(profileItem)}<div className="version-label nav-label">KNOWLEDGE BASE · PHASE 4</div></div>
    </aside>
    {mobileOpen && <button type="button" className="mobile-scrim" aria-label="Close navigation" onClick={onClose} />}
  </>;
}
