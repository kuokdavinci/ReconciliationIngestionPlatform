"use client";

import { useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Topbar } from "@/components/layout/topbar";
import { PageSection } from "@/components/ui/page-section";
import { ReviewPacketCard } from "@/components/review-center/review-packet-card";
import { ReviewSummaryDrawer } from "@/components/review-center/review-summary-drawer";
import { GuidedReviewModal } from "@/components/review-center/guided-review-modal";
import { useToast } from "@/components/ui/toast";
import { useReviewPackets } from "@/components/review-center/use-review-packets";
import type { ReviewPacket } from "@/types/review-center";
import styles from "@/components/review-center/review-center.module.css";

function ReviewCenterContent() {
  const searchParams = useSearchParams();
  const requestedId = searchParams.get("packet");
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
      <Topbar title="Review Center" subtitle="Approve pending packets, validate mapping readiness, and activate the next runtime safely." />

      <PageSection>
        <div className={styles.layout}>
          <div className={styles.leftColumn}>
            <div className={styles.sectionIntro}>
              <h3 className={styles.eyebrow}>
                Pending Review Items
              </h3>
              <p className={styles.introText}>
                {packets.length} draft mappings and format changes still require operator approval before runtime activation.
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
      </PageSection>

      <GuidedReviewModal
        open={guidedOpen}
        onClose={() => {
          setGuidedOpen(false);
          setGuidedPacket(null);
        }}
        onRefresh={handleRefresh}
        packet={guidedPacket ?? selectedPacket}
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
