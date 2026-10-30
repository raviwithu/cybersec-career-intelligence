import { lazy, Suspense, useId, useMemo } from "react";

import { Badge, Loading } from "./components";
import { DIAGRAM_KIND_LABELS, DIAGRAM_NODE_TYPE_LABELS, diagramSteps, isRenderableDiagram } from "./knowledgeDiagramLayout";

// The graph library is downloaded only when a diagram is shown.
const KnowledgeDiagramCanvas = lazy(() => import("./KnowledgeDiagramCanvas"));

export const VARIANT_LABELS = { vulnerable: "⚠ Vulnerable", secure: "✓ Secure" };

function prefersReducedMotion() {
  try { return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; }
}

export function DiagramNotice({ count = 1 }) {
  return <p className="kd-notice" role="note">{count === 1 ? "A diagram" : `${count} diagrams`} could not be displayed because the definition is invalid.</p>;
}

export default function KnowledgeDiagram({ diagram }) {
  const stepsId = useId();
  const reduceMotion = useMemo(prefersReducedMotion, []);
  if (!isRenderableDiagram(diagram)) return <DiagramNotice />;
  const steps = diagramSteps(diagram);
  const title = diagram.title || DIAGRAM_KIND_LABELS[diagram.kind] || "Diagram";
  return <figure className={`kd-figure kd-variant-${diagram.variant || "neutral"}`}>
    <figcaption className="kd-caption">
      <strong>{title}</strong>
      <span className="kd-kind">{DIAGRAM_KIND_LABELS[diagram.kind] || "Flow"}</span>
      {VARIANT_LABELS[diagram.variant] && <Badge tone={diagram.variant === "secure" ? "mint" : "rose"}>{VARIANT_LABELS[diagram.variant]}</Badge>}
    </figcaption>
    <Suspense fallback={<Loading label="Loading diagram" />}><KnowledgeDiagramCanvas diagram={diagram} label={`${title} diagram`} describedBy={stepsId} /></Suspense>
    <details className="kd-steps" open={reduceMotion}>
      <summary>Text version of this diagram</summary>
      <div id={stepsId}>
        {steps.length ? <ol aria-label={`${title} steps`}>{steps.map((step) => <li key={step.key}>{step.from} → {step.to}{step.label ? `: ${step.label}` : ""}</li>)}</ol>
          : <ul aria-label={`${title} components`}>{diagram.nodes.map((node) => <li key={node.id}>{node.label} ({DIAGRAM_NODE_TYPE_LABELS[node.type] || "Service"})</li>)}</ul>}
        {diagram.boundaries?.length ? <p>Trust boundaries: {diagram.boundaries.map((boundary) => `${boundary.label} (${diagram.nodes.filter((node) => node.boundary === boundary.id).map((node) => node.label).join(", ") || "empty"})`).join("; ")}.</p> : null}
      </div>
    </details>
  </figure>;
}
