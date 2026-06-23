"use client";

import { useCallback, useEffect, useMemo, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Topbar } from "@/components/layout/topbar";
import { PageSection } from "@/components/ui/page-section";
import { ReviewPacketCard } from "@/components/review-center/review-packet-card";
import { ReviewSummaryDrawer } from "@/components/review-center/review-summary-drawer";
import { GuidedReviewModal } from "@/components/review-center/guided-review-modal";
import { useToast } from "@/components/ui/toast";
import * as api from "@/lib/api/review-center";
import type { ReviewPacket } from "@/types/review-center";
import styles from "@/components/review-center/review-center.module.css";

function ReviewCenterContent() {
  const searchParams = useSearchParams();
  const [packets, setPackets] = useState<ReviewPacket[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedPacketDetail, setSelectedPacketDetail] = useState<ReviewPacket | null>(null);
  const [guidedOpen, setGuidedOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const { showToast } = useToast();

  const refreshPackets = useCallback(async () => {
    try {
      const response = await api.listReviewPackets();
      const nextPackets = [...(response.packets ?? [])].filter(p => String(p.status).toUpperCase() === "PENDING").sort((a, b) => String(b.createdAt || "").localeCompare(String(a.createdAt || "")));
      setPackets(nextPackets);
      setSelectedId((current) => {
        const requestedPacket = searchParams.get("packet");
        if (requestedPacket && nextPackets.some((packet) => packet._id === requestedPacket)) {
          return requestedPacket;
        }
        if (current && nextPackets.some((packet) => packet._id === current)) {
          return current;
        }
        return nextPackets[0]?._id ?? null;
      });
      return nextPackets;
    } catch {
      showToast("Failed to load review packets from backend", "error");
      setPackets([]);
      setSelectedId(null);
      return [];
    } finally {
      setLoading(false);
    }
  }, [searchParams]);

  useEffect(() => {
    let cancelled = false;

    async function bootstrapPackets() {
      try {
        const response = await api.listReviewPackets();
        if (cancelled) return;
        const nextPackets = [...(response.packets ?? [])].filter(p => String(p.status).toUpperCase() === "PENDING").sort((a, b) => String(b.createdAt || "").localeCompare(String(a.createdAt || "")));
        setPackets(nextPackets);
        setSelectedId((current) => {
          const requestedPacket = searchParams.get("packet");
          if (requestedPacket && nextPackets.some((packet) => packet._id === requestedPacket)) {
            return requestedPacket;
          }
          if (current && nextPackets.some((packet) => packet._id === current)) {
            return current;
          }
          return nextPackets[0]?._id ?? null;
        });
      } catch {
        if (cancelled) return;
        showToast("Failed to load review packets from backend", "error");
        setPackets([]);
        setSelectedId(null);
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void bootstrapPackets();
    return () => {
      cancelled = true;
    };
  }, [searchParams]);

  useEffect(() => {
    if (!selectedId) return;
    const fallback = packets.find((packet) => packet._id === selectedId) ?? null;
    api.getReviewPacket(selectedId)
      .then((response) => setSelectedPacketDetail(response.packet))
      .catch(() => setSelectedPacketDetail(fallback));
  }, [packets, selectedId]);

  const selectedPacket = useMemo(() => {
    if (!selectedId) return null;
    if (selectedPacketDetail?._id === selectedId) return selectedPacketDetail;
    return packets.find((packet) => packet._id === selectedId) ?? null;
  }, [packets, selectedId, selectedPacketDetail]);

  const pendingCount = useMemo(() => packets.length, [packets]);

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
                {pendingCount} draft mappings and format changes still require operator approval before runtime activation.
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
              onOpenReview={() => setGuidedOpen(true)}
            />
          </div>
        </div>
      </PageSection>

      <GuidedReviewModal
        key={selectedPacket?._id ?? "empty"}
        packet={selectedPacket}
        open={guidedOpen}
        onClose={() => setGuidedOpen(false)}
        onRefresh={refreshPackets}
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
