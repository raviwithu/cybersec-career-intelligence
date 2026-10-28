import { useState } from "react";

import { Badge, PageHeader } from "./components";
import AutomatedResearchPage from "./AutomatedResearchPage";
import ResearchAdminPage from "./ResearchAdminPage";

const tabs = [
  ["manual", "Manual Submission", "Paste, upload, or preview a source"],
  ["bulk-jsearch", "Bulk JSearch", "Run a saved JSearch collection"],
  ["automated", "Automated Research", "Manage approved source schedules"],
  ["research-sources", "Research Sources", "Review registered collection endpoints"],
  ["saved-searches", "Saved Searches", "Create and manage search criteria"],
  ["collection-history", "Collection History", "Inspect completed collection runs"],
];

export default function ResearchIngestionPage({ onOpenReview, initialTab = "manual" }) {
  const [tab, setTab] = useState(initialTab);

  function content() {
    if (tab === "manual") return <ResearchAdminPage />;
    if (tab === "automated") return <AutomatedResearchPage onOpenReview={onOpenReview} initialTab="overview" />;
    if (tab === "research-sources") return <AutomatedResearchPage onOpenReview={onOpenReview} initialTab="sources" />;
    if (tab === "collection-history") return <AutomatedResearchPage onOpenReview={onOpenReview} initialTab="runs" />;
    return <AutomatedResearchPage onOpenReview={onOpenReview} initialTab="job-search" />;
  }

  return <>
    <PageHeader eyebrow="RESEARCH ADMIN / INGESTION" title="Research Ingestion" description="Use one workspace for manual evidence, bulk JSearch collection, approved automated sources, saved searches, and collection history."><Badge tone="violet">Administrator workspace</Badge></PageHeader>
    <div className="ingestion-tabs" role="tablist" aria-label="Research ingestion sections">{tabs.map(([id, label, description]) => <button type="button" role="tab" aria-selected={tab === id} className={tab === id ? "active" : ""} key={id} onClick={() => setTab(id)}><strong>{label}</strong><small>{description}</small></button>)}</div>
    <div className="ingestion-content">{content()}</div>
  </>;
}
