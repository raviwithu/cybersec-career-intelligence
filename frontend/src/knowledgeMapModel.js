import { hierarchy, tree } from "d3-hierarchy";

// Pure state helpers for the Security Knowledge Map. The page keeps one immutable state object:
// nodes by id, loaded child ids per node, parent links, the expanded set and branch paging.

export const ROOT_ID = "root";
export const TOPIC_PAGE_SIZE = 50;
export const DOMAIN_PALETTE_SIZE = 6;
export const BRANCHES = {
  foundations: { label: "Foundations", icon: "▤" },
  security: { label: "Security", icon: "◆" },
  vulnerabilities: { label: "Common Vulnerabilities", icon: "⚠" },
};
export const NODE_WIDTH = 260;
const NODE_ROW_GAP = 52;
const NODE_COLUMN_GAP = 310;
const EXPANDABLE_TYPES = new Set(["root", "domain", "child-domain", "branch"]);

export const domainNodeId = (domainId) => `domain:${domainId}`;
export const branchNodeId = (domainId, branch) => `branch:${domainId}:${branch}`;
export const topicNodeId = (domainId, branch, topicKey) => `topic:${domainId}:${branch}:${topicKey}`;
const moreNodeId = (branchId) => `more:${branchId}`;
const emptyNodeId = (parentId) => `empty:${parentId}`;

export function initialMapState() {
  return { nodes: {}, children: {}, parents: {}, expanded: {}, paging: {} };
}

export function isExpandable(node) {
  return Boolean(node) && EXPANDABLE_TYPES.has(node.type);
}

function domainNode(domain, parent, index) {
  const topLevel = parent.type === "root";
  return { id: domainNodeId(domain.id), type: topLevel ? "domain" : "child-domain", label: domain.name, domainId: domain.id, slug: domain.slug, childDomainCount: domain.child_domain_count, topicCount: domain.placed_topic_count, palette: topLevel ? index % DOMAIN_PALETTE_SIZE : parent.palette };
}

function topicNode(branch, item) {
  return { id: topicNodeId(branch.domainId, branch.branch, item.topic_key), type: "topic", label: item.name, topicKey: item.topic_key, topicId: item.id, description: item.short_description || "", placementCount: item.placement_count ?? item.placements?.length ?? 1, domainId: branch.domainId, branch: branch.branch, palette: branch.palette };
}

function withChildren(state, parentId, childNodes) {
  const nodes = { ...state.nodes };
  const parents = { ...state.parents };
  childNodes.forEach((node) => { nodes[node.id] = node; parents[node.id] = parentId; });
  return { ...state, nodes, parents, children: { ...state.children, [parentId]: childNodes.map((node) => node.id) } };
}

function emptyNode(parentId) {
  return { id: emptyNodeId(parentId), type: "empty", label: "No published topics yet" };
}

export function applyRoot(state, data) {
  const root = { id: ROOT_ID, type: "root", label: data.root.name };
  const next = { ...state, nodes: { ...state.nodes, [ROOT_ID]: root }, expanded: { ...state.expanded, [ROOT_ID]: true } };
  return withChildren(next, ROOT_ID, data.domains.map((domain, index) => domainNode(domain, root, index)));
}

export function applyDomainChildren(state, domainId, data) {
  const parent = state.nodes[domainId];
  const childNodes = data.nodes.map((item, index) => item.node_type === "branch"
    ? { id: branchNodeId(item.domain_id, item.branch), type: "branch", label: item.label, branch: item.branch, domainId: item.domain_id, topicCount: item.topic_count, palette: parent.palette }
    : domainNode(item, parent, index));
  return withChildren(state, domainId, childNodes.length ? childNodes : [emptyNode(domainId)]);
}

function topicIds(state, branchId) {
  return (state.children[branchId] || []).filter((id) => state.nodes[id]?.type === "topic");
}

function withTopics(state, branchId, topics, paging) {
  const branch = state.nodes[branchId];
  const known = new Set(topicIds(state, branchId));
  const existing = topicIds(state, branchId).map((id) => state.nodes[id]);
  const added = topics.map((item) => topicNode(branch, item)).filter((node) => !known.has(node.id) && known.add(node.id));
  const remaining = paging.total - paging.loaded;
  const more = remaining > 0 ? [{ id: moreNodeId(branchId), type: "more", label: `Load more (${remaining} remaining)`, branchId }] : [];
  const listed = [...existing, ...added];
  const next = withChildren(state, branchId, listed.length || more.length ? [...listed, ...more] : [emptyNode(branchId)]);
  return { ...next, paging: { ...next.paging, [branchId]: paging } };
}

// Appends one page from GET /knowledge-map/domains/{id}/branches/{branch}/topics, skipping topics already listed.
export function applyTopicPage(state, branchId, page) {
  return withTopics(state, branchId, page.items, { total: page.total, loaded: page.offset + page.items.length });
}

// Lists a topic that search revealed but that lies beyond the loaded pages. Later pages skip it.
export function ensureTopic(state, branchId, topic) {
  const branch = state.nodes[branchId];
  if (state.nodes[topicNodeId(branch.domainId, branch.branch, topic.topic_key)]) return state;
  return withTopics(state, branchId, [topic], state.paging[branchId] || { total: 0, loaded: 0 });
}

export function nextTopicOffset(state, branchId) {
  return state.paging[branchId]?.loaded || 0;
}

export function expand(state, ids) {
  return { ...state, expanded: { ...state.expanded, ...Object.fromEntries(ids.map((id) => [id, true])) } };
}

export function collapse(state, id) {
  const expanded = { ...state.expanded };
  delete expanded[id];
  return { ...state, expanded };
}

export function collapseAll(state) {
  return { ...state, expanded: state.nodes[ROOT_ID] ? { [ROOT_ID]: true } : {} };
}

export function pathTo(state, id) {
  const path = [];
  for (let current = id; current && state.nodes[current]; current = state.parents[current]) path.unshift(current);
  return path;
}

// The nearest ancestor (or the node itself) that is still visible, used after a collapse hides the selection.
export function visibleAncestor(state, id) {
  const path = pathTo(state, id);
  const hiddenAt = path.findIndex((nodeId, index) => index < path.length - 1 && !state.expanded[nodeId]);
  return hiddenAt === -1 ? id : path[hiddenAt];
}

// Nested visible structure. Expanded nodes whose children are not loaded yet get a loading or error placeholder.
export function visibleTree(state, status = {}) {
  function build(id) {
    const node = state.nodes[id];
    if (!state.expanded[id] || !isExpandable(node)) return { id, node, children: [] };
    const childIds = state.children[id];
    if (!childIds) {
      const failed = status[id] instanceof Error;
      return { id, node, children: [{ id: `status:${id}`, node: { id: `status:${id}`, type: failed ? "error" : "loading", label: failed ? "Could not load. Retry" : "Loading…", targetId: id }, children: [] }] };
    }
    return { id, node, children: childIds.map(build) };
  }
  return state.nodes[ROOT_ID] ? build(ROOT_ID) : null;
}

// Depth-first rows for the tree view, with the ARIA level, position and set size of each row.
export function visibleRows(treeRoot) {
  const rows = [];
  function walk(item, level, parentId, posinset, setsize) {
    rows.push({ id: item.id, node: item.node, level, parentId, posinset, setsize, childIds: item.children.map((child) => child.id) });
    item.children.forEach((child, index) => walk(child, level + 1, item.id, index + 1, item.children.length));
  }
  if (treeRoot) walk(treeRoot, 1, null, 1, 1);
  return rows;
}

// Left-to-right tidy tree layout of the visible nodes. It depends only on structure, never on selection.
export function layoutTree(treeRoot) {
  if (!treeRoot) return { positions: [], edges: [] };
  const root = hierarchy(treeRoot, (item) => item.children);
  tree().nodeSize([NODE_ROW_GAP, NODE_COLUMN_GAP])(root);
  return {
    positions: root.descendants().map((item) => ({ id: item.data.id, node: item.data.node, x: item.y, y: item.x })),
    edges: root.links().map(({ source, target }) => ({ id: `${source.data.id}->${target.data.id}`, source: source.data.id, target: target.data.id })),
  };
}
