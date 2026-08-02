/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Topbar } from "@/components/layout/topbar";
import { PageSection } from "@/components/ui/page-section";
import { Panel } from "@/components/ui/panel";
import { Button } from "@/components/ui/button";
import { PendingActionsList } from "@/components/mapping-studio/pending-actions-list";
import { MappingConfigsTable } from "@/components/mapping-studio/mapping-configs-table";
import { MappingStudioWizard } from "@/components/mapping-studio/mapping-studio-wizard";
import { useToast } from "@/components/ui/toast";
import * as api from "@/lib/api/mapping-studio";
import { getCurrentActor } from "@/lib/actor";

export default function MappingStudioPage() {
  const [configs, setConfigs] = useState<Record<string, unknown>[]>([]);
  const [pendingActions, setPendingActions] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [showWizard, setShowWizard] = useState(false);
  const [reviewUploading, setReviewUploading] = useState(false);
  const pendingRef = useRef<HTMLDivElement>(null);
  const reviewFileRef = useRef<HTMLInputElement>(null);
  const { showToast } = useToast();

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [mappingsRes] = await Promise.all([
        api.listMappings("MOMO"),
      ]);
      setConfigs(mappingsRes.mappings ?? []);
      const pending = (mappingsRes.mappings ?? []).filter((m: Record<string, unknown>) => m.status === "PENDING_APPROVAL");
      setPendingActions(pending.map((m: Record<string, unknown>) => ({
        _id: m._id,
        draftMappingId: m._id,
        title: `Approve ${m.partner} Config v${m.version}`,
        reason: `Draft mapping for ${m.sheetName ?? "Sheet1"} (${m.fieldMappingCount ?? 0} fields)`,
        status: m.status,
        partner: m.partner,
        mappingCount: m.fieldMappingCount,
      })));
    } catch {
      showToast("Failed to load mapping configurations from backend", "error");
      setConfigs([]);
      setPendingActions([]);
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    const timer = setTimeout(() => {
      void loadData();
    }, 0);
    return () => clearTimeout(timer);
  }, [loadData]);

  const approvedConfigs = configs.filter((c) => c.status === "APPROVED");

  const handleApprove = async (id: string) => {
    try {
      await api.approveMapping(id, getCurrentActor());
      showToast(`Config ${id} approved!`, "success");
      setPendingActions((prev) => prev.filter((a) => a.draftMappingId !== id));
      await loadData();
    } catch {
      showToast(`Failed to approve config ${id}`, "error");
    }
  };

  const handleReject = async (id: string) => {
    try {
      await api.rejectMapping(id, getCurrentActor());
      showToast(`Config ${id} rejected.`, "info");
      setPendingActions((prev) => prev.filter((a) => a.draftMappingId !== id));
      await loadData();
    } catch {
      showToast(`Failed to reject config ${id}`, "error");
    }
  };

  const handleReviewUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setReviewUploading(true);
    showToast("Analyzing uploaded file and preparing a review item...");
    try {
      const result = await api.aiGenerateMapping("MOMO", file);
      if (result.reviewItemId) {
        showToast("Review item created. Opening Review Center.");
        window.location.hash = "review-center";
      } else {
        showToast("Review item created.", "success");
        setShowWizard(true);
      }
    } catch (err: any) {
      showToast(err.message || "Upload analysis failed", "error");
    } finally {
      setReviewUploading(false);
      if (e.target) e.target.value = "";
    }
  };

  const todayStr = new Date().toISOString().split("T")[0];

  if (loading) {
    return (
      <div>
        <Topbar title="Mapping Studio" subtitle="Configure field mappings and transformations" />
        <PageSection><div style={{ padding: 32, textAlign: "center", color: "var(--text-muted)" }}>Loading mapping configurations...</div></PageSection>
      </div>
    );
  }

  return (
    <div>
      <Topbar title="Mapping Studio" subtitle="Configure field mappings and transformations" />

      {/* Hidden file input for review upload */}
      <input
        ref={reviewFileRef}
        type="file"
        accept=".xlsx,.xls,.csv"
        style={{ display: "none" }}
        onChange={handleReviewUpload}
      />

      <PageSection>
        <Panel header={
          <div>
            <p style={{ margin: 0, fontSize: 11, color: "var(--text-muted)", fontWeight: 700, letterSpacing: "0.05em" }}>
              Draft Workflow
            </p>
            <h2 style={{ margin: 0, fontSize: 20, color: "#fff" }}>Mapping Studio</h2>
            <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--text-muted)" }}>
              Select sample, review the draft mapping, validate output, then submit for review.
            </p>
          </div>
        }>
          <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", marginBottom: 16 }}>
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Partner: <strong style={{ color: "var(--text-primary)" }}>MOMO</strong></span>
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Date: <strong style={{ color: "var(--text-primary)" }}>{todayStr}</strong></span>
            <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
              <Button
                variant="primary"
                onClick={() => reviewFileRef.current?.click()}
                disabled={reviewUploading}
              >
                {reviewUploading ? "Processing..." : "Upload File For Review"}
              </Button>
              <Button
                variant="secondary"
                onClick={() => setShowWizard(v => !v)}
              >
                {showWizard ? "Close Mapping Studio" : "Open Mapping Studio"}
              </Button>
            </div>
          </div>
        </Panel>
      </PageSection>

      {showWizard && (
        <PageSection>
          <MappingStudioWizard
            initialPartner="MOMO"
            onNavigateReview={() => {
              setShowWizard(false);
              setTimeout(() => pendingRef.current?.scrollIntoView({ behavior: "smooth" }), 100);
            }}
          />
        </PageSection>
      )}

      {pendingActions.length > 0 && (
        <PageSection>
          <div ref={pendingRef}>
            <Panel header={<strong>Pending Approval</strong>}>
              <PendingActionsList
                actions={pendingActions as never}
                onApprove={handleApprove}
                onReject={handleReject}
              />
            </Panel>
          </div>
        </PageSection>
      )}

      <PageSection>
        <Panel header={
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
            <div>
              <strong>Active Runtime Configurations</strong>
              <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--text-muted)" }}>
                Approved configurations currently available to the parser.
              </p>
            </div>
            <span style={{ fontSize: 22, color: "var(--brand-primary)" }}>⚙</span>
          </div>
        }>
          <MappingConfigsTable configs={approvedConfigs as never} />
        </Panel>
      </PageSection>
    </div>
  );
}
