"use client";

import styles from "./reconciliation.module.css";
import { Panel } from "@/components/ui/panel";

export function RunStatusPanelSkeleton() {
  return (
    <Panel>
      <div className={`${styles.statusPanelRow} ${styles.skeletonPulse}`} style={{ height: 56, borderRadius: 8 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, width: "30%" }}>
          <div className={styles.skeletonText} style={{ width: "80%" }}></div>
          <div className={styles.skeletonText} style={{ width: "40%", height: 16 }}></div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, width: "20%", alignItems: "flex-end" }}>
          <div className={styles.skeletonText} style={{ width: "60%", height: 20 }}></div>
          <div className={styles.skeletonText} style={{ width: "80%" }}></div>
        </div>
      </div>
    </Panel>
  );
}

export function SummaryStripSkeleton() {
  return (
    <div className={styles.summaryGrid}>
      {[1, 2, 3, 4, 5].map((i) => (
        <div key={i} className={`${styles.summaryCard} ${styles.skeletonPulse}`} style={{ height: 86, borderColor: "rgba(255,255,255,0.03)" }}>
          <div className={styles.skeletonText} style={{ width: "50%", height: 11 }}></div>
          <div className={styles.skeletonText} style={{ width: "70%", height: 28, marginTop: 8 }}></div>
        </div>
      ))}
    </div>
  );
}

export function InsightGridSkeleton() {
  return (
    <div className={styles.insightLoadingWrap}>
      <div className={styles.insightLoadingBanner}>
        <span className={styles.insightLoadingDot}></span>
        <strong>AI is synthesizing reconciliation signals</strong>
        <span>Ranking the highest-impact operator cards for this batch.</span>
      </div>
      <div className={styles.insightColumns}>
        {[1, 2, 3].map((col) => (
        <div key={col} className={styles.insightColumn}>
          <div className={styles.insightCards}>
            {[1].map((card) => (
              <div
                key={card}
                className={`${styles.insightCard} ${styles.skeletonPulse} ${styles.insightSkeletonCard}`}
                style={{ borderColor: "rgba(255, 255, 255, 0.05)", background: "rgba(0, 0, 0, 0.1)" }}
              >
                <div className={styles.skeletonTitle} style={{ width: "40%" }}></div>
                <div style={{ display: "flex", justifyContent: "space-between", margin: "6px 0" }}>
                  <div className={styles.skeletonText} style={{ width: "100px", height: 18 }}></div>
                  <div className={styles.skeletonText} style={{ width: "60px" }}></div>
                </div>
                <div className={styles.insightSkeletonMetrics}>
                  <div className={styles.skeletonText} style={{ width: "74px", height: 18 }}></div>
                  <div className={styles.skeletonText} style={{ width: "92px", height: 18 }}></div>
                  <div className={styles.skeletonText} style={{ width: "68px", height: 18 }}></div>
                </div>
                <div className={styles.skeletonText} style={{ width: "90%", height: 14, marginTop: 12 }}></div>
                <div className={styles.skeletonText} style={{ width: "85%", height: 14 }}></div>
                <div className={styles.skeletonText} style={{ width: "70%", height: 14 }}></div>
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: "auto" }}>
                  <div className={styles.skeletonText} style={{ width: "80px" }}></div>
                  <div className={styles.skeletonText} style={{ width: "50px", height: 16 }}></div>
                </div>
              </div>
            ))}
          </div>
        </div>
        ))}
      </div>
    </div>
  );
}

export function EvidenceTableSkeleton() {
  return (
    <div className={styles.ledgerTableWrap}>
      <div className={styles.skeletonPulse} style={{ height: 40, background: "rgba(255,255,255,0.02)", borderBottom: "1px solid rgba(255,255,255,0.04)" }}></div>
      {[1, 2, 3, 4, 5].map((i) => (
        <div
          key={i}
          className={styles.skeletonPulse}
          style={{
            height: 48,
            display: "flex",
            alignItems: "center",
            padding: "0 12px",
            gap: 16,
            borderBottom: "1px solid rgba(255,255,255,0.03)",
          }}
        >
          <div style={{ width: 16, height: 16, backgroundColor: "rgba(255,255,255,0.04)", borderRadius: 3 }}></div>
          <div style={{ width: 60, height: 18, backgroundColor: "rgba(255,255,255,0.04)", borderRadius: 4 }}></div>
          <div style={{ width: 120, height: 18, backgroundColor: "rgba(255,255,255,0.04)", borderRadius: 4 }}></div>
          <div style={{ width: 100, height: 18, backgroundColor: "rgba(255,255,255,0.04)", borderRadius: 4 }}></div>
          <div style={{ flex: 1, height: 14, backgroundColor: "rgba(255,255,255,0.03)", borderRadius: 4 }}></div>
          <div style={{ width: 80, height: 16, backgroundColor: "rgba(255,255,255,0.04)", borderRadius: 4 }}></div>
          <div style={{ width: 80, height: 16, backgroundColor: "rgba(255,255,255,0.04)", borderRadius: 4 }}></div>
        </div>
      ))}
    </div>
  );
}
