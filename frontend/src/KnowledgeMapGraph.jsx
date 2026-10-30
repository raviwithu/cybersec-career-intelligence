import { memo, useEffect, useMemo, useRef } from "react";
import { Background, Handle, Position, ReactFlow, ReactFlowProvider, useReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { NODE_WIDTH, isExpandable } from "./knowledgeMapModel";
import { nodeClassName, nodeIcon } from "./KnowledgeMapTree";

const DEFAULT_VIEWPORT = { x: 40, y: 260, zoom: 1 };
const PAN_STEP = 160;

// Graph nodes are rendered by us: one focusable button per node. Enter selects; Space expands or collapses.
const MapNode = memo(function MapNode({ data }) {
  const { node, selected, open, badge, onActivate, onToggle } = data;
  const expandable = isExpandable(node);
  const inert = node.type === "empty" || node.type === "loading";
  return <div className={nodeClassName(node, selected)} style={{ width: NODE_WIDTH }}>
    <Handle type="target" position={Position.Left} isConnectable={false} className="km-handle" />
    <button type="button" className="km-node-main" disabled={inert} aria-pressed={selected} aria-expanded={expandable ? open : undefined} onClick={() => onActivate(node)} onKeyDown={(event) => { if (event.key === " " && expandable) { event.preventDefault(); onToggle(node.id); } }}>
      <span className="km-node-icon" aria-hidden="true">{nodeIcon(node)}</span><span className="km-node-label" title={node.label}>{node.label}</span>{badge && <span className="km-pending-badge">{badge}</span>}
    </button>
    {expandable && <button type="button" className="km-node-toggle" tabIndex={-1} aria-label={`${open ? "Collapse" : "Expand"} ${node.label}`} onClick={() => onToggle(node.id)}>{open ? "−" : "+"}</button>}
    <Handle type="source" position={Position.Right} isConnectable={false} className="km-handle" />
  </div>;
});

const nodeTypes = { mapNode: MapNode };

function GraphCanvas({ layout, expanded, selectedId, focusRequest, onActivate, onToggle, commandRef, reduceMotion, badgeFor }) {
  const flow = useReactFlow();
  const duration = reduceMotion ? 0 : 250;
  // Positions come from the memoised layout; selection only changes node data, never positions.
  const nodes = useMemo(() => layout.positions.map((item) => ({ id: item.id, type: "mapNode", position: { x: item.x, y: item.y }, data: { node: item.node, selected: item.id === selectedId, open: Boolean(expanded[item.id]), badge: badgeFor?.(item.node) || null, onActivate, onToggle } })), [layout, expanded, selectedId, onActivate, onToggle, badgeFor]);
  const edges = useMemo(() => layout.edges.map((edge) => ({ ...edge, type: "smoothstep", focusable: false })), [layout]);

  useEffect(() => {
    commandRef.current = {
      zoomIn: () => flow.zoomIn({ duration }),
      zoomOut: () => flow.zoomOut({ duration }),
      fit: () => flow.fitView({ duration, padding: 0.15, maxZoom: 1 }),
      reset: () => flow.setViewport(DEFAULT_VIEWPORT, { duration }),
      pan: (dx, dy) => { const viewport = flow.getViewport(); flow.setViewport({ ...viewport, x: viewport.x + dx * PAN_STEP, y: viewport.y + dy * PAN_STEP }, { duration }); },
    };
    return () => { commandRef.current = null; };
  }, [flow, duration, commandRef]);

  // Centre on nodes selected from outside the canvas (search, breadcrumb, toolbar), once they are laid out.
  const centred = useRef(null);
  useEffect(() => {
    if (!focusRequest || centred.current === focusRequest) return;
    const target = layout.positions.find((item) => item.id === focusRequest.id);
    if (!target) return;
    centred.current = focusRequest;
    flow.setCenter(target.x + NODE_WIDTH / 2, target.y, { zoom: flow.getZoom(), duration });
  }, [focusRequest, layout]);

  return <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} defaultViewport={DEFAULT_VIEWPORT} fitView fitViewOptions={{ padding: 0.15, maxZoom: 1 }} minZoom={0.2} maxZoom={2} nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} nodesFocusable={false} edgesFocusable={false} zoomOnDoubleClick={false} onlyRenderVisibleElements>
    <Background gap={24} size={1} color="var(--km-grid)" />
  </ReactFlow>;
}

export default function KnowledgeMapGraph(props) {
  return <div className="km-graph" aria-label="Security Knowledge Map graph" role="group"><ReactFlowProvider><GraphCanvas {...props} /></ReactFlowProvider></div>;
}
