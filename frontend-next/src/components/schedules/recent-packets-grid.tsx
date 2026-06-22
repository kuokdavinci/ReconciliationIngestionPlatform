"use client";

import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { RecentPacket } from "@/types/schedules";
import styles from "./schedules.module.css";

const sevMap: Record<string, "low" | "medium" | "high" | "critical"> = {
  low: "low", medium: "medium", high: "high", critical: "critical",
};

interface Props {
  packets: RecentPacket[];
}

export function RecentPacketsGrid({ packets }: Props) {
  const router = useRouter();

  if (packets.length === 0) {
    return (
      <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)" }}>
        No recent automation packets.
      </div>
    );
  }

  return (
    <div className={styles.packetsGrid}>
      {packets.map((p) => (
        <div key={p._id} className={styles.packetCard}>
          <div className={styles.packetHeader}>
            <div>
              <p className={styles.packetEyebrow}>{p.fetchMethod}</p>
              <h3 className={styles.packetPartner}>{p.partner}</h3>
            </div>
            <Badge severity={sevMap[p.riskSummary?.severity ?? "medium"]}>
              {(p.riskSummary?.severity ?? "MEDIUM").toUpperCase()}
            </Badge>
          </div>
          <p className={styles.packetFile}>{p.fileName}</p>
          <div className={styles.packetBadgeRow}>
            <Badge severity={p.status === "PENDING" ? "medium" : "low"}>{p.status}</Badge>
            {p.sourceType ? <Badge severity="neutral">{p.sourceType}</Badge> : null}
            {p.decisionMode ? <Badge severity="neutral">{p.decisionMode}</Badge> : null}
          </div>
          <div className={styles.packetRecommendation}>
            <strong className={styles.packetRecommendationTitle}>Agent recommendation</strong>
            <p className={styles.packetRecommendationText}>{p.recommendedAction?.reason ?? "-"}</p>
          </div>
          {p._id && (
            <Button
              variant="primary"
              style={{ width: "100%", justifyContent: "center", marginTop: "auto" }}
              onClick={() => router.push(`/review-center?packet=${encodeURIComponent(p._id)}`)}
            >
              Open Review
            </Button>
          )}
        </div>
      ))}
    </div>
  );
}
