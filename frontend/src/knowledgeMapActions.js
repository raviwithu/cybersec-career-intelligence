// Labels for knowledge map proposal actions and a small line diff for before/after review. No React here, so the
// Knowledge Review page can use it without loading Knowledge Map Management.

export const MAP_ACTION_LABELS = {
  CREATE_TOPIC: "Create topic", PLACE_TOPIC: "Place topic", UNPLACE_TOPIC: "Remove placement", MOVE_TOPIC: "Move topic",
  REORDER_TOPICS: "Reorder branch", SET_PARENT_TOPIC: "Set parent topic", ADD_TOPIC_RELATIONSHIP: "Add relationship",
  REMOVE_TOPIC_RELATIONSHIP: "Remove relationship", DEACTIVATE_TOPIC: "Deactivate topic", UPDATE_CAREER_LEVELS: "Career levels",
  RESTORE_VERSION: "Restore version",
};

export const MAP_ACTIONS = Object.keys(MAP_ACTION_LABELS).filter((action) => !["CREATE_TOPIC", "ADD_TOPIC_RELATIONSHIP"].includes(action));

export function isMapProposal(proposal) {
  return MAP_ACTIONS.includes(proposal.action) || (proposal.action === "CREATE_TOPIC" && Boolean(proposal.proposed_content?.placements?.length));
}

function lines(value) {
  return value == null ? [] : JSON.stringify(value, null, 2).split("\n");
}

// Longest-common-subsequence line diff: [{ kind: "same" | "removed" | "added", text }].
export function lineDiff(before, after) {
  const a = lines(before);
  const b = lines(after);
  const table = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i -= 1) for (let j = b.length - 1; j >= 0; j -= 1) table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
  const result = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { result.push({ kind: "same", text: a[i] }); i += 1; j += 1; }
    else if (table[i + 1][j] >= table[i][j + 1]) { result.push({ kind: "removed", text: a[i] }); i += 1; }
    else { result.push({ kind: "added", text: b[j] }); j += 1; }
  }
  while (i < a.length) { result.push({ kind: "removed", text: a[i] }); i += 1; }
  while (j < b.length) { result.push({ kind: "added", text: b[j] }); j += 1; }
  return result;
}
