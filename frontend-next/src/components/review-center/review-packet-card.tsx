"use client";

import { Badge } from "@/components/ui/badge";
import type { ReviewPacket } from "@/types/review-center";
import styles from "./review-center.module.css";

const sevMap: Record<string, "low" | "medium" | "high" | "critical"> = {
  low: "low",
  medium: "medium",
  high: "high",
  critical: "critical",
};

interface Props {
  packet: ReviewPacket;
  isSelected: boolean;
  onSelect: (id: string) => void;
}

export function ReviewPacketCard({ packet, isSelected, onSelect }: Props) {
  const riskSev = sevMap[packet.riskSummary?.severity ?? "medium"];
  const passCount = packet.validationGates.filter((g) => g.status === "pass").length;
  const isBatchFatal = packet.qualityGateStatus === "FAIL";

  return (
    <div
      onClick={() => onSelect(packet._id)}
      className={`${styles.packetCard} ${isSelected ? styles.packetCardSelected : ""}`}
    >
      <div className={styles.packetCardHeader}>
        {isBatchFatal ? <Badge severity="critical">BATCH FATAL</Badge> : null}
        <Badge severity={riskSev}>{packet.riskSummary?.severity ?? "MEDIUM"} RISK</Badge>
        <span className={styles.packetChecks}>{passCount}/{packet.validationGates.length} checks</span>
      </div>
      <strong className={styles.packetTitle}>{packet.fileName}</strong>
      <p className={styles.packetReason}>{packet.recommendedAction?.reason ?? "Awaiting reviewer decision."}</p>
      <div className={styles.packetMeta}>
        <span>{packet.parseStrategy?.sheetName}</span>
        <span>Row {packet.parseStrategy?.startRow}</span>
        {packet.parseStrategy?.fieldMappingCount != null && (
          <span>{packet.parseStrategy.fieldMappingCount} fields</span>
        )}
      </div>
    </div>
  );
}
