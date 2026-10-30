import { memo, useMemo } from "react";
import { Controls, Handle, MarkerType, Position, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { DIAGRAM_NODE_HEIGHT, DIAGRAM_NODE_TYPE_LABELS, DIAGRAM_NODE_WIDTH, layoutDiagram } from "./knowledgeDiagramLayout";

// Read-only rendering of validated diagram JSON. Every label is a React text node; content supplies no styles.

function Handles() {
  return <>
    <Handle type="target" id="left" position={Position.Left} isConnectable={false} className="kd-handle" />
    <Handle type="source" id="left" position={Position.Left} isConnectable={false} className="kd-handle" />
    <Handle type="target" id="right" position={Position.Right} isConnectable={false} className="kd-handle" />
    <Handle type="source" id="right" position={Position.Right} isConnectable={false} className="kd-handle" />
  </>;
}

const DiagramNode = memo(function DiagramNode({ data }) {
  const { node } = data;
  return <div className={`kd-node kd-node-${node.type || "service"}`} style={{ width: DIAGRAM_NODE_WIDTH, minHeight: DIAGRAM_NODE_HEIGHT }}>
    <Handles />
    <span className="kd-node-type">{DIAGRAM_NODE_TYPE_LABELS[node.type] || "Service"}</span>
    <strong title={node.label}>{node.label}</strong>
  </div>;
});

const BoundaryNode = memo(function BoundaryNode({ data }) {
  return <div className="kd-boundary" style={{ width: data.width, height: data.height }}><span>{data.label}</span></div>;
});

const AnchorNode = memo(function AnchorNode() {
  return <div className="kd-anchor"><Handles /></div>;
});

const LifelineNode = memo(function LifelineNode({ data }) {
  return <div className="kd-lifeline" style={{ height: data.height }} />;
});

const nodeTypes = { node: DiagramNode, boundary: BoundaryNode, anchor: AnchorNode, lifeline: LifelineNode };

export default function KnowledgeDiagramCanvas({ diagram, label, describedBy }) {
  const { nodes, edges } = useMemo(() => {
    const layout = layoutDiagram(diagram);
    return {
      nodes: layout.nodes.map((item) => ({ id: item.id, type: item.kind, position: { x: item.x, y: item.y }, data: item, zIndex: item.kind === "boundary" || item.kind === "lifeline" ? -1 : 1, draggable: false, selectable: false, focusable: false })),
      edges: layout.edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, sourceHandle: edge.sourceHandle, targetHandle: edge.targetHandle, label: edge.label, type: edge.straight ? "straight" : "smoothstep", markerEnd: { type: MarkerType.ArrowClosed }, focusable: false, className: "kd-edge" })),
    };
  }, [diagram]);
  return <div className="kd-canvas" role="group" aria-label={label} aria-describedby={describedBy}>
    <ReactFlowProvider>
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.12, maxZoom: 1 }} minZoom={0.25} maxZoom={2} nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} nodesFocusable={false} edgesFocusable={false} zoomOnDoubleClick={false} zoomOnScroll={false} preventScrolling={false}>
        <Controls showInteractive={false} />
      </ReactFlow>
    </ReactFlowProvider>
  </div>;
}
