import { hierarchy, tree } from "d3-hierarchy";

// Pure state helpers for the Security Knowledge Map. The page keeps one immutable state object:
// nodes by id, loaded child ids per node, parent links and the expanded set.
// Domains hold sub-domains and topics; a topic holds the Foundations, Security and Common Vulnerabilities branches, unless it is itself in Common Vulnerabilities,
// and each branch holds smaller topics, to any depth. A topic also holds a group node for each of Learn, Playbook and
// Reference that has published content, and each group's facet nodes open one section in the topic panel.

export const ROOT_ID = "root";
export const DOMAIN_PALETTE_SIZE = 6;
export const BRANCHES = {
  foundations: { label: "Foundations", icon: "▤" },
  security: { label: "Security", icon: "◆" },
  vulnerabilities: { label: "Common Vulnerabilities", icon: "⚠" },
};
// Each group's sections, in display order; the keys are the topic panel's tab ids.
const LEARN_SECTIONS = {
  overview: { label: "Overview", icon: "◎" },
  how_it_works: { label: "How It Works", icon: "⚙" },
  attack_surfaces: { label: "Attack Surface", icon: "⚠" },
  architecture: { label: "Architecture", icon: "▦" },
  real_world_examples: { label: "Real-World CVEs", icon: "◆" },
};
export const PLAYBOOK_SECTIONS = {
  code_examples: { label: "Example Code", icon: "‹›" },
  mitigations: { label: "Mitigations", icon: "✓" },
  source_review: { label: "Source Review", icon: "⌕" },
  dynamic_review: { label: "Dynamic Review", icon: "⇄" },
  information_gathering: { label: "Information Gathering", icon: "◇" },
  ai_cicd_skill: { label: "CI/CD Scan", icon: "⚙" },
  ai_dynamic_skill: { label: "Dynamic Analysis", icon: "◉" },
};
const REFERENCE_SECTIONS = {
  career_levels: { label: "Career Levels", icon: "⇢" },
  related: { label: "Related Topics", icon: "⇄" },
  references: { label: "References", icon: "▤" },
};
export const SECTION_GROUPS = {
  learn: { label: "Learn", sections: LEARN_SECTIONS },
  playbook: { label: "Playbook", sections: PLAYBOOK_SECTIONS },
  reference: { label: "Reference", sections: REFERENCE_SECTIONS },
};

export function groupOfSection(section) {
  return Object.keys(SECTION_GROUPS).find((group) => SECTION_GROUPS[group].sections[section]) || null;
}

export function sectionInfo(section) {
  return SECTION_GROUPS[groupOfSection(section)]?.sections[section];
}

export const NODE_WIDTH = 260;
const NODE_ROW_GAP = 52;
const NODE_COLUMN_GAP = 310;
const EXPANDABLE_TYPES = new Set(["root", "domain", "child-domain", "topic", "branch", "section-group"]);

export const domainNodeId = (domainId) => `domain:${domainId}`;
// A topic appears at most once per domain, so the domain and topic key identify its node.
export const topicNodeId = (domainId, topicKey) => `topic:${domainId}:${topicKey}`;
export const branchNodeId = (domainId, topicKey, branch) => `branch:${domainId}:${topicKey}:${branch}`;
export const sectionGroupNodeId = (domainId, topicKey, group) => `group:${domainId}:${topicKey}:${group}`;
export const facetNodeId = (domainId, topicKey, section) => `facet:${domainId}:${topicKey}:${section}`;
const emptyNodeId = (parentId) => `empty:${parentId}`;

// Where a topic sits: its domains, then each parent topic followed by the branch of it the next one sits in.
export function placementLabel(placement) {
  const ancestors = placement.ancestors || [];
  const topics = ancestors.flatMap((topic, index) => [topic.name, BRANCHES[index + 1 < ancestors.length ? ancestors[index + 1].branch : placement.branch]?.label]);
  return [...placement.domain_path.map((domain) => domain.name), ...topics].filter(Boolean).join(" › ");
}

export function initialMapState() {
  return { nodes: {}, children: {}, parents: {}, expanded: {} };
}

export function isExpandable(node) {
  return Boolean(node) && EXPANDABLE_TYPES.has(node.type);
}

// Topics and their section facets both open the wide topic panel.
export function opensTopicPanel(node) {
  return node?.type === "topic" || node?.type === "facet";
}

function domainNode(domain, parent, index) {
  const topLevel = parent.type === "root";
  return { id: domainNodeId(domain.id), type: topLevel ? "domain" : "child-domain", label: domain.name, domainId: domain.id, slug: domain.slug, childDomainCount: domain.child_domain_count, topicCount: domain.placed_topic_count, palette: topLevel ? index % DOMAIN_PALETTE_SIZE : parent.palette };
}

// parent is the domain node or branch node the topic sits in; branch nodes carry their parent topic.
function topicNode(parent, item) {
  return { id: topicNodeId(parent.domainId, item.topic_key), type: "topic", label: item.name, topicKey: item.topic_key, topicId: item.id, description: item.short_description || "", placementCount: item.placement_count ?? 1, contextNote: item.context_note || "", hasChildren: Boolean(item.has_children), domainId: parent.domainId, parentTopicId: parent.type === "branch" ? parent.parentTopicId : null, branch: parent.type === "branch" ? parent.branch : null, palette: parent.palette };
}

function withChildren(state, parentId, childNodes) {
  const nodes = { ...state.nodes };
  const parents = { ...state.parents };
  childNodes.forEach((node) => { nodes[node.id] = node; parents[node.id] = parentId; });
  return { ...state, nodes, parents, children: { ...state.children, [parentId]: childNodes.map((node) => node.id) } };
}

function emptyNode(parentId, label = "No published topics yet") {
  return { id: emptyNodeId(parentId), type: "empty", label };
}

export function applyRoot(state, data) {
  const root = { id: ROOT_ID, type: "root", label: data.root.name };
  const next = { ...state, nodes: { ...state.nodes, [ROOT_ID]: root }, expanded: { ...state.expanded, [ROOT_ID]: true } };
  return withChildren(next, ROOT_ID, data.domains.map((domain, index) => domainNode(domain, root, index)));
}

// GET /knowledge-map/domains/{id}/children: sub-domains, then the topics placed directly in the domain.
export function applyDomainChildren(state, domainId, data) {
  const parent = state.nodes[domainId];
  const childNodes = data.nodes.map((item, index) => (item.node_type === "topic" ? topicNode(parent, item) : domainNode(item, parent, index)));
  return withChildren(state, domainId, childNodes.length ? childNodes : [emptyNode(domainId)]);
}

// GET /knowledge-map/domains/{id}/topics/{topicId}/children: the topic's three branches, each with its topics.
export function applyTopicChildren(state, topicId, data) {
  const topic = state.nodes[topicId];
  const branches = data.branches.map((item) => ({ id: branchNodeId(topic.domainId, topic.topicKey, item.branch), type: "branch", label: item.label, branch: item.branch, domainId: topic.domainId, parentTopicId: topic.topicId, parentTopicKey: topic.topicKey, topicCount: item.topic_count, palette: topic.palette }));
  const available = new Set(data.sections || []);
  const groups = Object.entries(SECTION_GROUPS).map(([group, { label, sections }]) => {
    const members = Object.keys(sections).filter((section) => available.has(section));
    return { group, members, node: { id: sectionGroupNodeId(topic.domainId, topic.topicKey, group), type: "section-group", group, label, domainId: topic.domainId, topicKey: topic.topicKey, parentTopicKey: topic.topicKey, topicNodeId: topicId, sectionCount: members.length } };
  }).filter((item) => item.members.length);
  const children = [...branches, ...groups.map((item) => item.node)];
  // A topic in Common Vulnerabilities has no branches, so with no sections either it would expand to nothing.
  let next = withChildren(state, topicId, children.length ? children : [emptyNode(topicId, "No published sections yet")]);
  data.branches.forEach((item, index) => {
    const branch = branches[index];
    const topics = item.items.map((child) => topicNode(branch, child));
    next = withChildren(next, branch.id, topics.length ? topics : [emptyNode(branch.id)]);
  });
  groups.forEach(({ group, members, node }) => {
    next = withChildren(next, node.id, members.map((section) => ({ id: facetNodeId(topic.domainId, topic.topicKey, section), type: "facet", label: sectionInfo(section).label, section, group, domainId: topic.domainId, topicKey: topic.topicKey, topicNodeId: topicId })));
  });
  return next;
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
