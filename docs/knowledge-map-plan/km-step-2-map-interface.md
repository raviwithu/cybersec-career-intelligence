# Knowledge Map Step KM-2 — Interactive Map Interface

Read `00-shared-context.md` first. Requires Step KM-1 merged. Frontend only, except bug fixes to Step KM-1 endpoints.

## Goal

A public **Security Knowledge Map** page that expands the published hierarchy one level at a time, with an accessible
tree-view alternative. Selecting a topic shows a minimal details placeholder (full panel is Step KM-3).

## 1. Assessment

- Read `App.jsx`, `AppShell.jsx`, `SidebarNavigation.jsx`, `api.js`, `useApi.js`, `components.jsx`, `styles.css`
  and the existing theme handling. Follow their patterns for routing, API calls, loading and error states.
- Record the baseline.

## 2. Navigation

- Add `{ id: "knowledge-map", label: "Security Knowledge Map" }` to the **Explore** group, after Knowledge Base,
  with an icon in the existing style. Route it in `App.jsx` the same way as other views.
- Support deep links in whatever form existing views use (for example a selected topic key), so a URL can reopen a topic.
- Update `SidebarNavigation.test.jsx` expectations for the new item only.

## 3. Dependencies

Add `@xyflow/react` and `d3-hierarchy` with exact pinned versions compatible with React 19. Confirm the production build
size impact and report it. Lazy-load the map page (`React.lazy`) so other pages do not pay for the graph library.

## 4. Components (new files)

- `KnowledgeMapPage.jsx` — page layout, toolbar, state, two-panel layout.
- `KnowledgeMapGraph.jsx` — `@xyflow/react` canvas; nodes laid out left-to-right with `d3-hierarchy` `tree()`.
- `KnowledgeMapTree.jsx` — accessible tree view (WAI-ARIA `tree` / `treeitem` with `aria-expanded`, `aria-level`).
- `knowledgeMapApi.js` functions in `api.js` (or alongside, following existing structure).

### Behaviour
- Initial view: root and top-level domains only.
- Expanding a node fetches its children on demand (Step KM-1 endpoints) and caches them in page state.
  Branch topic lists load 50 at a time with a "Load more" node.
- Controls: expand, collapse, expand all children of the selected node (one level, loaded on demand; never the whole map),
  collapse all, zoom in/out, fit to screen, reset view, pan, navigate to parent.
- Search box (debounced, Step KM-1 search endpoint): selecting a result expands only the nodes on that result's path and
  selects the topic. If a topic has several placements, let the user choose the path.
- Breadcrumb of the selected node's path; each crumb is clickable.
- "Graph" / "List" toggle switches between graph and tree view; both share the same expansion state.
  Remember the choice in `localStorage` (wrapped in try/catch).
- Selecting a topic opens the right-hand panel showing name, short description, all placements (cross-domain links),
  and an empty-state note "Full topic details arrive in a later release." (replaced in Step KM-3).
- Empty states: domain with no placed topics → "No published topics yet"; fetch failures → existing error component with retry.

### Visual design
- Node types: root, domain, child domain, branch, topic. Keep labels short; no descriptions inside nodes.
- Branch colours: Foundations blue, Security green, Common Vulnerabilities red; domains use a category palette.
  Each branch node also shows a text label and icon so colour is never the only signal.
- Selected node has a visible border and focus ring. Define colours as CSS variables with light and dark values that
  meet WCAG AA contrast.
- Respect `prefers-reduced-motion` (disable animated transitions and fitView animation).
- Two-panel layout on desktop; at narrow widths the details panel becomes a drawer and the list view is the default.

### Keyboard
- Tree view: arrow keys move, Right/Left expand/collapse, Enter selects, Home/End jump.
- Graph view: all toolbar controls reachable by Tab; nodes focusable with Enter to select and Space to expand.
- Everything works without drag-to-pan.

### Performance
- Memoise node and edge arrays; changing selection must not re-layout the graph.
- Re-layout only the expanded subtree when children load.
- Test with a generated branch of 1,000 topics (paged) and report interaction responsiveness.

## 5. Tests (`frontend/tests/KnowledgeMap.test.jsx`)

Mock the API. Cover:
1. Root and domains render from API data (no hardcoded domain names).
2. Expanding a domain requests and shows child domains then branch nodes.
3. Branch nodes are scoped to the expanded domain.
4. Expanding a branch lists topics; "Load more" requests the next page.
5. Selecting a topic opens the panel and shows the breadcrumb.
6. Search reveals the path to a result without expanding unrelated nodes.
7. Tree view keyboard navigation and ARIA attributes.
8. Collapse hides descendants; navigate-to-parent selects the parent.
9. Error state and retry.
10. Sidebar shows the new item; all existing navigation tests still pass.

Graph canvas internals may be hard to test in jsdom; test behaviour through the tree view and the toolbar, and keep
graph-specific logic (layout, node building) in pure functions with unit tests.

## 6. Docs

Add a "Map interface" section to `docs/knowledge-map.md`: interactions, accessibility, lazy loading.

## Out of scope

Topic detail content, admin features, any backend write.
