import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fetchKnowledgeContractTopic, fetchKnowledgeMapBranchTopics, fetchKnowledgeMapChildren, fetchKnowledgeMapPlacements, fetchKnowledgeMapRoot, searchKnowledgeMap } from "./api";
import { EmptyState, ErrorState, Loading, PageHeader } from "./components";
import KnowledgeMapTopicPanel from "./KnowledgeMapTopicPanel";
import KnowledgeMapTree from "./KnowledgeMapTree";
import { BRANCHES, ROOT_ID, TOPIC_PAGE_SIZE, applyDomainChildren, applyRoot, applyTopicPage, branchNodeId, collapse, collapseAll, domainNodeId, ensureTopic, expand, initialMapState, isExpandable, layoutTree, nextTopicOffset, pathTo, topicNodeId, visibleAncestor, visibleRows, visibleTree } from "./knowledgeMapModel";

// The graph library is only downloaded when the graph view is shown.
const KnowledgeMapGraph = lazy(() => import("./KnowledgeMapGraph"));

const VIEW_MODE_KEY = "cybersec-career-intelligence.knowledge-map-view";
const SEARCH_DEBOUNCE_MS = 300;
const MIN_SEARCH_LENGTH = 2;

function mediaMatches(query) {
  try { return typeof window.matchMedia === "function" && window.matchMedia(query).matches; } catch { return false; }
}

function readViewMode() {
  try {
    const stored = window.localStorage.getItem(VIEW_MODE_KEY);
    if (stored === "graph" || stored === "list") return stored;
  } catch { /* storage unavailable */ }
  return mediaMatches("(max-width: 800px)") ? "list" : "graph";
}

function topicFromHash() {
  const query = window.location.hash.split("?")[1];
  return query ? new URLSearchParams(query).get("topic") || "" : "";
}

// Deep links take the form #knowledge-map?topic=<topic_key>. replaceState keeps history clean and fires no hashchange.
function writeTopicToHash(topicKey) {
  if (window.location.hash.split("?")[0] !== "#knowledge-map") return;
  const next = `#knowledge-map${topicKey ? `?topic=${encodeURIComponent(topicKey)}` : ""}`;
  if (window.location.hash !== next) window.history.replaceState(window.history.state, "", next);
}

function placementLabel(placement) {
  return [...placement.domain_path.map((domain) => domain.name), placement.label].join(" › ");
}

function NodeDetails({ node, state, placements, onReveal, onSelectTopic, onNavigate }) {
  if (!node) return null;
  if (node.type === "topic") return <KnowledgeMapTopicPanel
    node={node}
    breadcrumb={pathTo(state, node.id).map((id) => state.nodes[id].label)}
    placements={placements}
    isCurrentPlacement={(placement) => topicNodeId(placement.domain_path[placement.domain_path.length - 1].id, placement.branch, node.topicKey) === node.id}
    onReveal={(placement) => onReveal({ id: node.topicId, topic_key: node.topicKey, name: node.label, short_description: node.description }, placement)}
    onSelectTopic={onSelectTopic}
    onNavigate={onNavigate} />;
  if (node.type === "branch") return <>
    <p className="eyebrow">BRANCH · {state.nodes[state.parents[node.id]]?.label}</p>
    <h2><span aria-hidden="true">{BRANCHES[node.branch]?.icon} </span>{node.label}</h2>
    <p className="km-details-copy">{node.topicCount} published {node.topicCount === 1 ? "topic" : "topics"} in this branch.</p>
  </>;
  if (node.type === "domain" || node.type === "child-domain") {
    const childIds = state.children[node.id];
    return <>
      <p className="eyebrow">{node.type === "domain" ? "SECURITY DOMAIN" : "CHILD DOMAIN"}</p>
      <h2>{node.label}</h2>
      <p className="km-details-copy">{node.topicCount} published {node.topicCount === 1 ? "topic" : "topics"}{node.childDomainCount ? ` across ${node.childDomainCount} child ${node.childDomainCount === 1 ? "domain" : "domains"} and its branches` : ""}.</p>
      {childIds && state.nodes[childIds[0]]?.type === "empty" && <EmptyState title="No published topics yet" message="Topics appear here once a reviewed placement is published for this domain." />}
    </>;
  }
  return <>
    <p className="eyebrow">KNOWLEDGE MAP</p>
    <h2>{node.label}</h2>
    <p className="km-details-copy">{state.children[ROOT_ID]?.length || 0} security domains. Expand a domain to see its Foundations, Security and Common Vulnerabilities branches.</p>
  </>;
}

// admin (Knowledge Map Management only): { badgeFor(node) -> label or null, renderDetails(node, context) -> element }.
// The public page never receives it, so pending badges and admin actions never appear on the public map.
export default function KnowledgeMapPage({ onNavigate, admin = null }) {
  const [state, setMapState] = useState(initialMapState);
  // Async loaders read and write through this ref so sequential steps (search reveal) see each other's results.
  const stateRef = useRef(state);
  const update = useCallback((change) => { stateRef.current = change(stateRef.current); setMapState(stateRef.current); }, []);
  const [status, setStatus] = useState({});
  const inflight = useRef({});
  const [selectedId, setSelectedId] = useState(ROOT_ID);
  const [focusRequest, setFocusRequest] = useState(null);
  const [viewMode, setViewMode] = useState(readViewMode);
  const [panelOpen, setPanelOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState({ loading: false, error: null, items: null });
  const [pathChoice, setPathChoice] = useState(null);
  const [placements, setPlacements] = useState({ loading: false, error: null, items: [] });
  const deepLinkPending = useRef(Boolean(topicFromHash()));
  const commandRef = useRef(null);
  const reduceMotion = useMemo(() => mediaMatches("(prefers-reduced-motion: reduce)"), []);

  const setNodeStatus = useCallback((id, value) => setStatus((current) => {
    const next = { ...current };
    if (value) next[id] = value; else delete next[id];
    return next;
  }), []);

  // Loads a node's children once; concurrent callers share the request. Resolves to false on failure.
  const loadChildren = useCallback((id, { fresh = false } = {}) => {
    const current = stateRef.current;
    const node = current.nodes[id];
    if (!fresh && (id === ROOT_ID ? current.nodes[ROOT_ID] : !isExpandable(node) || current.children[id])) return Promise.resolve(Boolean(id === ROOT_ID || node));
    if (fresh && id !== ROOT_ID && !isExpandable(node)) return Promise.resolve(false);
    if (inflight.current[id]) return inflight.current[id];
    setNodeStatus(id, "loading");
    const request = id === ROOT_ID ? fetchKnowledgeMapRoot({ fresh }).then((data) => update((value) => applyRoot(value, data)))
      : node.type === "branch" ? fetchKnowledgeMapBranchTopics(node.domainId, node.branch, { offset: 0, limit: TOPIC_PAGE_SIZE }).then((page) => update((value) => applyTopicPage(value, id, page)))
        : fetchKnowledgeMapChildren(node.domainId, { fresh }).then((data) => update((value) => applyDomainChildren(value, id, data)));
    inflight.current[id] = request
      .then(() => { setNodeStatus(id, null); return true; }, (error) => { setNodeStatus(id, error); return false; })
      .finally(() => { delete inflight.current[id]; });
    return inflight.current[id];
  }, [update, setNodeStatus]);

  const loadMore = useCallback(async (branchId) => {
    const key = `more:${branchId}`;
    if (inflight.current[key]) return;
    const node = stateRef.current.nodes[branchId];
    setNodeStatus(key, "loading");
    inflight.current[key] = fetchKnowledgeMapBranchTopics(node.domainId, node.branch, { offset: nextTopicOffset(stateRef.current, branchId), limit: TOPIC_PAGE_SIZE })
      .then((page) => { update((value) => applyTopicPage(value, branchId, page)); setNodeStatus(key, null); })
      .catch((error) => { setNodeStatus(key, error); setNotice(`More topics could not be loaded: ${error.message}`); })
      .finally(() => { delete inflight.current[key]; });
  }, [update, setNodeStatus]);

  const selectNode = useCallback((id, centre = false) => {
    setSelectedId(id);
    if (stateRef.current.nodes[id]?.type === "topic") setPanelOpen(true);
    if (centre) setFocusRequest({ id });
  }, []);

  // Fetches a node's children again from the server and expands it (admin: after a domain is added, edited or moved).
  const reloadChildren = useCallback((id) => {
    if (!stateRef.current.nodes[id]) return Promise.resolve(false);
    update((value) => expand(value, [id]));
    return loadChildren(id, { fresh: true });
  }, [update, loadChildren]);
  const expandNode = useCallback((id) => { update((value) => expand(value, [id])); loadChildren(id); }, [update, loadChildren]);
  const collapseNode = useCallback((id) => {
    update((value) => collapse(value, id));
    setSelectedId((current) => visibleAncestor(stateRef.current, current));
  }, [update]);
  const toggleNode = useCallback((id) => (stateRef.current.expanded[id] ? collapseNode(id) : expandNode(id)), [collapseNode, expandNode]);

  const activateNode = useCallback((node) => {
    if (node.type === "more") loadMore(node.branchId);
    else if (node.type === "error") loadChildren(node.targetId);
    else if (node.type !== "empty" && node.type !== "loading") selectNode(node.id);
  }, [loadMore, loadChildren, selectNode]);

  // Expands only the nodes on one placement path, then selects the topic there. Other expanded nodes stay as they are.
  const reveal = useCallback(async (topic, placement) => {
    const domainIds = placement.domain_path.map((domain) => domainNodeId(domain.id));
    const leaf = placement.domain_path[placement.domain_path.length - 1];
    const branchId = branchNodeId(leaf.id, placement.branch);
    if (!(await loadChildren(ROOT_ID))) return;
    for (const id of [...domainIds, branchId]) {
      if (!stateRef.current.nodes[id] || !(await loadChildren(id))) { setNotice(`${topic.name} could not be shown under ${placementLabel(placement)}.`); return; }
    }
    update((value) => expand(ensureTopic(value, branchId, topic), [ROOT_ID, ...domainIds, branchId]));
    setNotice("");
    selectNode(topicNodeId(leaf.id, placement.branch, topic.topic_key), true);
  }, [loadChildren, update, selectNode]);

  const openTopicKey = useCallback(async (topicKey) => {
    try {
      const [topicPlacements, topic] = await Promise.all([fetchKnowledgeMapPlacements(topicKey), fetchKnowledgeContractTopic(topicKey)]);
      if (topicPlacements.length) await reveal({ id: topic.id, topic_key: topic.topic_key, name: topic.name, short_description: topic.description || "" }, topicPlacements[0]);
      else setNotice(`${topic.name} is not on the published map yet.`);
    } catch (error) {
      setNotice(`The linked topic could not be opened: ${error.message}`);
    } finally {
      deepLinkPending.current = false;
    }
  }, [reveal]);

  useEffect(() => {
    loadChildren(ROOT_ID).then((loaded) => { const topicKey = topicFromHash(); if (loaded && topicKey) openTopicKey(topicKey); else deepLinkPending.current = false; });
  }, []);

  const selectedNode = state.nodes[selectedId] || null;

  useEffect(() => {
    const onHashChange = () => { const topicKey = topicFromHash(); if (topicKey && topicKey !== stateRef.current.nodes[selectedId]?.topicKey) openTopicKey(topicKey); };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [selectedId, openTopicKey]);

  useEffect(() => { if (!deepLinkPending.current) writeTopicToHash(selectedNode?.topicKey || ""); }, [selectedNode?.topicKey]);

  useEffect(() => {
    if (!selectedNode?.topicKey) return undefined;
    let active = true;
    setPlacements({ loading: true, error: null, items: [] });
    fetchKnowledgeMapPlacements(selectedNode.topicKey)
      .then((items) => active && setPlacements({ loading: false, error: null, items }))
      .catch((error) => active && setPlacements({ loading: false, error, items: [] }));
    return () => { active = false; };
  }, [selectedNode?.topicKey]);

  useEffect(() => {
    const term = query.trim();
    setPathChoice(null);
    if (term.length < MIN_SEARCH_LENGTH) { setSearch({ loading: false, error: null, items: null }); return undefined; }
    let active = true;
    setSearch((current) => ({ ...current, loading: true, error: null }));
    const timer = setTimeout(() => {
      searchKnowledgeMap(term.slice(0, 100))
        .then((result) => active && setSearch({ loading: false, error: null, items: result.items }))
        .catch((error) => active && setSearch({ loading: false, error, items: null }));
    }, SEARCH_DEBOUNCE_MS);
    return () => { active = false; clearTimeout(timer); };
  }, [query]);

  function chooseResult(result) {
    if (result.placements.length === 1) { setQuery(""); reveal(result, result.placements[0]); }
    else setPathChoice(result);
  }

  function changeViewMode(mode) {
    setViewMode(mode);
    try { window.localStorage.setItem(VIEW_MODE_KEY, mode); } catch { /* storage unavailable */ }
  }

  async function expandChildren() {
    const id = selectedId;
    if (!(await loadChildren(id))) return;
    const childIds = (stateRef.current.children[id] || []).filter((childId) => isExpandable(stateRef.current.nodes[childId]));
    update((value) => expand(value, [id, ...childIds]));
    childIds.forEach((childId) => loadChildren(childId));
  }

  function collapseEverything() {
    update(collapseAll);
    setSelectedId((current) => visibleAncestor(stateRef.current, current));
  }

  function selectParent() {
    const parentId = state.parents[selectedId];
    if (parentId) selectNode(parentId, true);
  }

  const treeRoot = useMemo(() => visibleTree(state, status), [state.nodes, state.children, state.expanded, status]);
  const rows = useMemo(() => visibleRows(treeRoot), [treeRoot]);
  const layout = useMemo(() => (viewMode === "graph" ? layoutTree(treeRoot) : null), [treeRoot, viewMode]);
  const breadcrumb = pathTo(state, selectedId);
  const selectedExpandable = isExpandable(selectedNode);
  const selectedOpen = Boolean(state.expanded[selectedId]);
  const graph = viewMode === "graph";
  const command = (name, ...args) => commandRef.current?.[name]?.(...args);
  const loadingCount = Object.values(status).filter((value) => value === "loading").length;

  const rootStatus = status[ROOT_ID];
  const header = admin ? null : <PageHeader eyebrow="EXPLORE" title="Security Knowledge Map" description="Expand security domains into Foundations, Security and Common Vulnerabilities, one level at a time. Only published, reviewed topics appear." />;
  if (!state.nodes[ROOT_ID]) return <>
    {header}
    {rootStatus instanceof Error ? <ErrorState error={rootStatus} onRetry={() => loadChildren(ROOT_ID)} /> : <Loading label="Loading the knowledge map" />}
  </>;

  return <div className="knowledge-map-page">
    {header}
    <section className="panel km-toolbar" role="toolbar" aria-label="Map controls">
      <div className="km-search">
        <label><span className="field-label">Search topics</span><input type="search" value={query} maxLength={100} placeholder="Name, alias or topic key" aria-describedby="km-search-hint" onChange={(event) => setQuery(event.target.value)} /></label>
        <small id="km-search-hint">Type at least {MIN_SEARCH_LENGTH} characters.</small>
        {(search.loading || search.error || search.items) && <div className="km-search-results" aria-live="polite">
          {search.loading ? <span className="muted-copy">Searching…</span>
            : search.error ? <span className="muted-copy">Search failed: {search.error.message}</span>
              : search.items.length === 0 ? <span className="muted-copy">No published topics match “{query.trim()}”.</span>
                : <ul aria-label="Search results">{search.items.map((result) => <li key={result.topic_key}><button type="button" onClick={() => chooseResult(result)}><strong>{result.name}</strong><small>{result.placements.length === 1 ? placementLabel(result.placements[0]) : `${result.placements.length} locations on the map`}</small></button></li>)}</ul>}
          {pathChoice && <div className="km-path-choice" role="group" aria-label={`Choose where to show ${pathChoice.name}`}><span className="field-label">Show {pathChoice.name} in</span>{pathChoice.placements.map((placement) => <button type="button" className="text-link" key={placementLabel(placement)} onClick={() => { setQuery(""); reveal(pathChoice, placement); }}>{placementLabel(placement)}</button>)}</div>}
        </div>}
      </div>
      <div className="km-toolbar-groups">
        <div className="km-view-toggle" role="group" aria-label="Map view">
          <button type="button" aria-pressed={graph} className={graph ? "active" : ""} onClick={() => changeViewMode("graph")}>Graph</button>
          <button type="button" aria-pressed={!graph} className={!graph ? "active" : ""} onClick={() => changeViewMode("list")}>List</button>
        </div>
        <div className="km-control-group" role="group" aria-label="Expansion">
          <button type="button" disabled={!selectedExpandable || selectedOpen} onClick={() => expandNode(selectedId)}>Expand</button>
          <button type="button" disabled={!selectedExpandable || !selectedOpen} onClick={() => collapseNode(selectedId)}>Collapse</button>
          <button type="button" disabled={!selectedExpandable} onClick={expandChildren}>Expand children</button>
          <button type="button" onClick={collapseEverything}>Collapse all</button>
          <button type="button" disabled={!state.parents[selectedId]} onClick={selectParent}>Go to parent</button>
        </div>
        <div className="km-control-group" role="group" aria-label="Viewport">
          <button type="button" disabled={!graph} aria-label="Zoom in" onClick={() => command("zoomIn")}>+</button>
          <button type="button" disabled={!graph} aria-label="Zoom out" onClick={() => command("zoomOut")}>−</button>
          <button type="button" disabled={!graph} onClick={() => command("fit")}>Fit</button>
          <button type="button" disabled={!graph} onClick={() => command("reset")}>Reset view</button>
          <button type="button" disabled={!graph} aria-label="Pan left" onClick={() => command("pan", 1, 0)}>◂</button>
          <button type="button" disabled={!graph} aria-label="Pan up" onClick={() => command("pan", 0, 1)}>▴</button>
          <button type="button" disabled={!graph} aria-label="Pan down" onClick={() => command("pan", 0, -1)}>▾</button>
          <button type="button" disabled={!graph} aria-label="Pan right" onClick={() => command("pan", -1, 0)}>▸</button>
        </div>
      </div>
    </section>
    <nav className="km-breadcrumb" aria-label="Selected path"><ol>{breadcrumb.map((id, index) => <li key={id}>{index === breadcrumb.length - 1 ? <span aria-current="location">{state.nodes[id].label}</span> : <button type="button" className="text-link" onClick={() => selectNode(id, true)}>{state.nodes[id].label}</button>}</li>)}</ol></nav>
    <p className="km-status" role="status" aria-live="polite">{notice || (loadingCount ? "Loading…" : "")}</p>
    <div className={`km-workspace ${selectedNode?.type === "topic" ? "topic-open" : ""}`}>
      <section className="panel km-canvas" aria-label={graph ? "Map graph" : "Map list"}>
        {graph
          ? <Suspense fallback={<Loading label="Loading the graph view" />}><KnowledgeMapGraph layout={layout} expanded={state.expanded} selectedId={selectedId} focusRequest={focusRequest} onActivate={activateNode} onToggle={toggleNode} commandRef={commandRef} reduceMotion={reduceMotion} badgeFor={admin?.badgeFor} /></Suspense>
          : <KnowledgeMapTree treeRoot={treeRoot} rows={rows} expanded={state.expanded} selectedId={selectedId} onActivate={activateNode} onToggle={toggleNode} badgeFor={admin?.badgeFor} />}
        {state.children[ROOT_ID]?.length === 0 && <EmptyState title="No active security domains" message="Domains appear here once they are active in Taxonomy Management." />}
      </section>
      <aside className={`panel km-details ${panelOpen ? "open" : ""}`} aria-label="Selected node details">
        <button type="button" className="km-details-close" aria-label="Close details" onClick={() => setPanelOpen(false)}>×</button>
        {admin && selectedNode && admin.renderDetails(selectedNode, { state, placements, loadChildren, reloadChildren })}
        <NodeDetails node={selectedNode} state={state} placements={placements} onReveal={reveal} onSelectTopic={openTopicKey} onNavigate={onNavigate} />
      </aside>
    </div>
  </div>;
}
