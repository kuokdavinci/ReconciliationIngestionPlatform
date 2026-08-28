"use client";

import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Topbar } from "@/components/layout/topbar";
import { PageSection } from "@/components/ui/page-section";
import { ReviewPacketCard } from "@/components/review-center/review-packet-card";
import { ReviewSummaryDrawer } from "@/components/review-center/review-summary-drawer";
import { GuidedReviewModal } from "@/components/review-center/guided-review-modal";
import { useToast } from "@/components/ui/toast";
import { useReviewPackets } from "@/components/review-center/use-review-packets";
import { QuarantineQueue } from "@/components/review-center/quarantine-queue";
import type { ReviewPacket } from "@/types/review-center";
import styles from "@/components/review-center/review-center.module.css";

function ReviewCenterContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const requestedId = searchParams.get("packet");
  const activeTab = searchParams.get("tab") === "quarantine" ? "quarantine" : "mapping";
  const isQuarantine = activeTab === "quarantine";
  const quarantinePacketId = searchParams.get("packetId") ?? undefined;
  const quarantineRunId = searchParams.get("postApprovalRunId") ?? undefined;
  const [guidedOpen, setGuidedOpen] = useState(false);
  const [guidedPacket, setGuidedPacket] = useState<ReviewPacket | null>(null);
  const { showToast } = useToast();

  const {
    packets,
    selectedId,
    selectedPacket,
    loading,
    setSelectedId,
    refreshPackets,
  } = useReviewPackets(requestedId);

  const handleRefresh = async () => {
    try {
      await refreshPackets();
    } catch {
      showToast("Failed to load review packets from backend", "error");
    }
  };

  return (
    <div>
      <Topbar
        title="Review Center"
        subtitle={isQuarantine
          ? "Review data rows held before persistence, inspect source evidence, and choose a bounded resolution."
          : "Approve pending packets, validate mapping readiness, and activate the next runtime safely."}
      />

      <nav className={styles.reviewTabs} aria-label="Review Center sections" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "mapping"}
          className={`${styles.reviewTab} ${activeTab === "mapping" ? styles.reviewTabActive : ""}`}
          onClick={() => router.push("/review-center")}
        >
          Review Packets
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "quarantine"}
          className={`${styles.reviewTab} ${activeTab === "quarantine" ? styles.reviewTabActive : ""}`}
          onClick={() => router.push("/review-center?tab=quarantine")}
        >
          Quarantine
        </button>
      </nav>

      <PageSection>
        {isQuarantine ? <QuarantineQueue initialReviewPacketId={quarantinePacketId} initialPostApprovalRunId={quarantineRunId} /> : (
          <div className={styles.layout}>
            <div className={styles.leftColumn}>
              <div className={styles.sectionIntro}>
                <h3 className={styles.eyebrow}>
                  Review Items
                </h3>
                <p className={styles.introText}>
                  {packets.length} draft mappings, format changes, or failed batch outcomes require operator attention.
                </p>
              </div>
              {loading ? (
                <div className={styles.emptyBlock}>Loading...</div>
              ) : packets.length === 0 ? (
                <div className={styles.emptyBlock}>
                  <p>No pending review items for this partner.</p>
                </div>
              ) : (
                packets.map((p) => (
                  <ReviewPacketCard key={p._id} packet={p} isSelected={selectedId === p._id} onSelect={(id) => setSelectedId(id)} />
                ))
              )}
            </div>

            <div className={styles.summaryShell}>
              <ReviewSummaryDrawer
                packet={selectedPacket}
                onOpenReview={() => {
                  setGuidedPacket(selectedPacket);
                  setGuidedOpen(true);
                }}
              />
            </div>
          </div>
        )}
      </PageSection>

      <GuidedReviewModal
        open={guidedOpen}
        onClose={() => {
          setGuidedOpen(false);
          setGuidedPacket(null);
        }}
        onRefresh={handleRefresh}
        packet={guidedPacket ?? selectedPacket}
        onOpenQuarantine={({ packetId, postApprovalRunId }) => {
          setGuidedOpen(false);
          setGuidedPacket(null);
          const params = new URLSearchParams({ tab: "quarantine" });
          if (packetId) params.set("packetId", packetId);
          if (postApprovalRunId) params.set("postApprovalRunId", postApprovalRunId);
          router.push(`/review-center?${params.toString()}`);
        }}
      />
    </div>
  );
}

export default function ReviewCenterPage() {
  return (
    <Suspense fallback={<div style={{ padding: 32, textAlign: "center", color: "var(--text-muted)" }}>Loading review center...</div>}>
      <ReviewCenterContent />
    </Suspense>
  );
}
