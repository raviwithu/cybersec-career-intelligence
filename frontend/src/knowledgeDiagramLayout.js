// Pure layout for validated diagram JSON (D8). The backend validates diagrams; this module re-checks the shape
// so a malformed diagram is hidden instead of breaking the page, then positions nodes for the read-only canvas.

export const DIAGRAM_NODE_WIDTH = 170;
export const DIAGRAM_NODE_HEIGHT = 46;
const COLUMN_GAP = 230;
const ROW_GAP = 76;
const BOUNDARY_PADDING = 18;
const BOUNDARY_HEADER = 22;
const LANE_GAP = 210;
const MESSAGE_GAP = 54;
const MESSAGE_TOP = 92;

export const DIAGRAM_KIND_LABELS = { architecture: "Architecture", sequence: "Sequence", trust_boundary: "Trust boundaries", attack_path: "Attack path", flow: "Flow" };
export const DIAGRAM_NODE_TYPE_LABELS = { actor: "Actor", service: "Service", datastore: "Data store", control: "Security control", external: "External system" };

const isText = (value) => typeof value === "string" && value.length > 0;

export function isRenderableDiagram(diagram) {
  if (!diagram || typeof diagram !== "object" || !Array.isArray(diagram.nodes) || !diagram.nodes.length) return false;
  if (!diagram.nodes.every((node) => node && isText(node.id) && isText(node.label))) return false;
  const ids = new Set(diagram.nodes.map((node) => node.id));
  if (ids.size !== diagram.nodes.length) return false;
  const edges = diagram.edges || [];
  return Array.isArray(edges) && edges.every((edge) => edge && ids.has(edge.from) && ids.has(edge.to));
}

// Edges in reading order: explicit order first, then the order they were written.
export function orderedEdges(diagram) {
  return (diagram.edges || []).map((edge, index) => ({ ...edge, index })).sort((a, b) => (a.order ?? Infinity) - (b.order ?? Infinity) || a.index - b.index);
}

// The text alternative: one line per edge, in edge order.
export function diagramSteps(diagram) {
  const labels = Object.fromEntries(diagram.nodes.map((node) => [node.id, node.label]));
  return orderedEdges(diagram).map((edge) => ({ key: `${edge.index}`, from: labels[edge.from], to: labels[edge.to], label: edge.label || "" }));
}

// Longest-path layering along edge order; repeated relaxation is bounded so cycles cannot loop forever.
function layers(diagram) {
  const layer = Object.fromEntries(diagram.nodes.map((node) => [node.id, 0]));
  const edges = orderedEdges(diagram).filter((edge) => edge.from !== edge.to);
  for (let pass = 0; pass < diagram.nodes.length; pass += 1) {
    let changed = false;
    edges.forEach((edge) => { if (layer[edge.to] < layer[edge.from] + 1 && layer[edge.from] + 1 < diagram.nodes.length) { layer[edge.to] = layer[edge.from] + 1; changed = true; } });
    if (!changed) break;
  }
  return layer;
}

// Layered left-to-right layout. Each boundary gets its own horizontal band, so a boundary's region never covers
// nodes that belong to another boundary.
function layeredLayout(diagram) {
  const layer = layers(diagram);
  const boundaries = diagram.boundaries || [];
  const groups = [...boundaries.map((boundary) => boundary.id), null];
  const groupOf = (node) => (node.boundary && boundaries.some((boundary) => boundary.id === node.boundary) ? node.boundary : null);
  const bandStart = {};
  let row = 0;
  groups.forEach((group) => {
    const members = diagram.nodes.filter((node) => groupOf(node) === group);
    if (!members.length) return;
    const perLayer = {};
    members.forEach((node) => { perLayer[layer[node.id]] = (perLayer[layer[node.id]] || 0) + 1; });
    bandStart[group] = row + (group ? 1 : 0);
    row = bandStart[group] + Math.max(...Object.values(perLayer)) + (group ? 0.4 : 0);
  });
  const used = {};
  const nodes = diagram.nodes.map((node) => {
    const group = groupOf(node);
    const slot = `${group}:${layer[node.id]}`;
    used[slot] = (used[slot] || 0) + 1;
    return { id: node.id, kind: "node", node, x: layer[node.id] * COLUMN_GAP, y: (bandStart[group] + used[slot] - 1) * ROW_GAP };
  });
  const regions = boundaries.map((boundary) => {
    const members = nodes.filter((item) => groupOf(item.node) === boundary.id);
    if (!members.length) return null;
    const left = Math.min(...members.map((item) => item.x)) - BOUNDARY_PADDING;
    const top = Math.min(...members.map((item) => item.y)) - BOUNDARY_PADDING - BOUNDARY_HEADER;
    const right = Math.max(...members.map((item) => item.x)) + DIAGRAM_NODE_WIDTH + BOUNDARY_PADDING;
    const bottom = Math.max(...members.map((item) => item.y)) + DIAGRAM_NODE_HEIGHT + BOUNDARY_PADDING;
    return { id: `boundary:${boundary.id}`, kind: "boundary", label: boundary.label, x: left, y: top, width: right - left, height: bottom - top };
  }).filter(Boolean);
  const edges = orderedEdges(diagram).map((edge) => ({ id: `edge:${edge.index}`, source: edge.from, target: edge.to, label: edge.label || "", sourceHandle: "right", targetHandle: "left" }));
  return { nodes: [...regions, ...nodes], edges };
}

// Sequence diagrams: one lane per node in declared order, one row per message in edge order.
function sequenceLayout(diagram) {
  const laneX = Object.fromEntries(diagram.nodes.map((node, index) => [node.id, index * LANE_GAP]));
  const steps = orderedEdges(diagram);
  const height = MESSAGE_TOP + steps.length * MESSAGE_GAP;
  const nodes = diagram.nodes.flatMap((node) => [
    { id: `lifeline:${node.id}`, kind: "lifeline", x: laneX[node.id] + DIAGRAM_NODE_WIDTH / 2 - 1, y: DIAGRAM_NODE_HEIGHT, height: height - DIAGRAM_NODE_HEIGHT },
    { id: node.id, kind: "node", node, x: laneX[node.id], y: 0 },
  ]);
  const edges = [];
  steps.forEach((edge, row) => {
    const y = MESSAGE_TOP + row * MESSAGE_GAP;
    const centre = (id) => laneX[id] + DIAGRAM_NODE_WIDTH / 2;
    const forward = laneX[edge.to] >= laneX[edge.from];
    const source = { id: `anchor:${edge.index}:from`, kind: "anchor", x: centre(edge.from), y };
    const target = { id: `anchor:${edge.index}:to`, kind: "anchor", x: edge.from === edge.to ? centre(edge.to) + 60 : centre(edge.to), y: edge.from === edge.to ? y + 20 : y };
    nodes.push(source, target);
    edges.push({ id: `edge:${edge.index}`, source: source.id, target: target.id, label: `${row + 1}. ${edge.label || ""}`.trim(), sourceHandle: forward ? "right" : "left", targetHandle: forward ? "left" : "right", straight: true });
  });
  return { nodes, edges };
}

export function layoutDiagram(diagram) {
  if (!isRenderableDiagram(diagram)) return { nodes: [], edges: [] };
  return diagram.kind === "sequence" ? sequenceLayout(diagram) : layeredLayout(diagram);
}
