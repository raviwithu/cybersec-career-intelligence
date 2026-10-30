import { useEffect, useMemo, useRef, useState } from "react";

import { BRANCHES, isExpandable } from "./knowledgeMapModel";

const INERT_TYPES = new Set(["empty", "loading"]);

export function nodeIcon(node) {
  if (node.type === "branch") return BRANCHES[node.branch]?.icon;
  return { root: "◎", domain: "◈", "child-domain": "↳", topic: "•", more: "+", error: "!", empty: "◌", loading: "…" }[node.type];
}

export function nodeClassName(node, selected) {
  return ["km-node", `km-node-${node.type}`, node.branch ? `km-branch-${node.branch}` : "", node.palette !== undefined ? `km-palette-${node.palette}` : "", selected ? "selected" : ""].filter(Boolean).join(" ");
}

// WAI-ARIA tree view of the visible map. One row holds focus at a time (roving tabindex).
export default function KnowledgeMapTree({ treeRoot, rows, expanded, selectedId, onActivate, onToggle, badgeFor }) {
  const [focusedId, setFocusedId] = useState(selectedId);
  const itemRefs = useRef({});
  const indexById = useMemo(() => Object.fromEntries(rows.map((row, index) => [row.id, index])), [rows]);
  const activeId = indexById[focusedId] !== undefined ? focusedId : indexById[selectedId] !== undefined ? selectedId : rows[0]?.id;

  // Follow selections made elsewhere (search, breadcrumb, toolbar) so keyboard focus starts there.
  useEffect(() => { setFocusedId(selectedId); }, [selectedId]);

  function moveTo(id) {
    if (id === undefined) return;
    setFocusedId(id);
    itemRefs.current[id]?.focus();
  }

  function onKeyDown(event, row) {
    const index = indexById[row.id];
    const open = Boolean(expanded[row.id]);
    const expandable = isExpandable(row.node);
    if (event.key === "ArrowDown") moveTo(rows[index + 1]?.id);
    else if (event.key === "ArrowUp") moveTo(rows[index - 1]?.id);
    else if (event.key === "Home") moveTo(rows[0]?.id);
    else if (event.key === "End") moveTo(rows[rows.length - 1]?.id);
    else if (event.key === "ArrowRight") { if (expandable && !open) onToggle(row.id); else if (open) moveTo(row.childIds[0]); }
    else if (event.key === "ArrowLeft") { if (expandable && open) onToggle(row.id); else moveTo(row.parentId ?? undefined); }
    else if (event.key === "Enter") { if (!INERT_TYPES.has(row.node.type)) onActivate(row.node); }
    else if (event.key === " ") { if (expandable) onToggle(row.id); }
    else return;
    event.preventDefault();
    event.stopPropagation();
  }

  function renderItem(item, level, posinset, setsize) {
    const { node } = item;
    const expandable = isExpandable(node);
    const open = Boolean(expanded[item.id]);
    const selected = item.id === selectedId;
    return <li key={item.id} role="treeitem" aria-level={level} aria-posinset={posinset} aria-setsize={setsize} aria-expanded={expandable ? open : undefined} aria-selected={selected} aria-busy={node.type === "loading" || undefined} tabIndex={item.id === activeId ? 0 : -1} ref={(element) => { itemRefs.current[item.id] = element; }} onKeyDown={(event) => onKeyDown(event, rows[indexById[item.id]])} onFocus={(event) => { if (event.target === event.currentTarget) setFocusedId(item.id); }} className="km-tree-item">
      <div className={`km-tree-row ${nodeClassName(node, selected)}`} style={{ "--km-depth": level - 1 }} onClick={(event) => { event.stopPropagation(); setFocusedId(item.id); if (!INERT_TYPES.has(node.type)) onActivate(node); }}>
        {expandable ? <span className="km-tree-toggle" aria-hidden="true" onClick={(event) => { event.stopPropagation(); onToggle(item.id); }}>{open ? "▾" : "▸"}</span> : <span className="km-tree-toggle" aria-hidden="true" />}
        <span className="km-node-icon" aria-hidden="true">{nodeIcon(node)}</span>
        <span className="km-tree-label">{node.label}</span>
        {node.type === "branch" && <small>{node.topicCount}</small>}
        {(node.type === "domain" || node.type === "child-domain") && <small>{node.topicCount} topics</small>}
        {node.type === "topic" && node.placementCount > 1 && <small>{node.placementCount} domains</small>}
        {badgeFor?.(node) && <span className="km-pending-badge">{badgeFor(node)}</span>}
      </div>
      {open && item.children.length > 0 && <ul role="group">{item.children.map((child, index) => renderItem(child, level + 1, index + 1, item.children.length))}</ul>}
    </li>;
  }

  if (!treeRoot) return null;
  return <ul className="km-tree" role="tree" aria-label="Security Knowledge Map">{renderItem(treeRoot, 1, 1, 1)}</ul>;
}
