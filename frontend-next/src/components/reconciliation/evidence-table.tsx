"use client";

import type { ReconciliationRow } from "@/types/reconciliation";
import { Badge } from "@/components/ui/badge";
import { PaginationBar } from "./pagination-bar";
import styles from "./reconciliation.module.css";

interface Props {
  rows: ReconciliationRow[];
  total: number;
  limit: number;
  offset: number;
  selectedRowId: string | null;
  selectedRows: Record<string, boolean>;
  onPageChange: (offset: number) => void;
  onLimitChange: (limit: number) => void;
  onSelectRow: (id: string) => void;
  onToggleCheck: (id: string) => void;
  onSetVisibleSelection: (rows: ReconciliationRow[], selected: boolean) => void;
  onSelectEvidence: (id: string) => void;
}

export function EvidenceTable({
  rows,
  total,
  limit,
  offset,
  selectedRowId,
  selectedRows,
  onPageChange,
  onLimitChange,
  onSelectRow,
  onToggleCheck,
  onSetVisibleSelection,
  onSelectEvidence,
}: Props) {
  const selectableRows = rows.filter((r) => r.reconciliationStatus !== "MATCHED");
  const allVisibleSelected = selectableRows.length > 0 && selectableRows.every(
    (r) => r.reconciliationStatus === "MATCHED" || selectedRows[r.partnerTxnId || r.internalTxnId || r.id]
  );

  return (
    <div>
      <style jsx>{`
        @media (max-width: 768px) {
          .desktopTable { display: none; }
        }
      `}</style>

      <div className={`desktopTable ${styles.desktopOnly} ${styles.ledgerTableWrap}`}>
      <table className={styles.ledgerTable}>
        <thead>
          <tr>
            <th className={styles.ledgerHeadCell} style={{ width: 40, textAlign: "center" }}>
              <input
                type="checkbox"
                checked={allVisibleSelected}
                onChange={(e) => onSetVisibleSelection(rows, e.target.checked)}
              />
            </th>
            <th className={styles.ledgerHeadCell}>Severity</th>
            <th className={styles.ledgerHeadCell}>Status</th>
            <th className={styles.ledgerHeadCell}>Txn ID</th>
            <th className={styles.ledgerHeadCell}>Internal Status</th>
            <th className={styles.ledgerHeadCell}>Partner Status</th>
            <th className={styles.ledgerHeadCell} style={{ textAlign: "right" }}>Internal Amt</th>
            <th className={styles.ledgerHeadCell} style={{ textAlign: "right" }}>Partner Amt</th>
            <th className={styles.ledgerHeadCell} style={{ textAlign: "right" }}>Delta</th>
            <th className={styles.ledgerHeadCell} style={{ width: 60, textAlign: "center" }}>Detail</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const id = row.partnerTxnId || row.internalTxnId || row.id;
            const isSelected = selectedRowId === id;
            const isChecked = Boolean(selectedRows[id]);
            const sev = row.severity ?? (row.reconciliationStatus === "MATCHED" ? "low" : row.reconciliationStatus.startsWith("MISSING") ? "high" : "medium");
            const delta = row.delta ?? Math.abs(Number(row.internalAmount ?? 0) - Number(row.partnerAmount ?? 0));
            const deltaDirection = Number((row.partnerAmount ?? 0) - (row.internalAmount ?? 0));

            return (
              <tr
                key={id}
                onClick={() => onSelectRow(id)}
                className={`${styles.ledgerRow} ${isSelected ? styles.ledgerRowSelected : ""}`}
              >
                <td className={styles.ledgerCell} style={{ textAlign: "center" }} onClick={(e) => e.stopPropagation()}>
                  {row.reconciliationStatus !== "MATCHED" && (
                    <input type="checkbox" checked={isChecked} onChange={() => onToggleCheck(id)} />
                  )}
                </td>
                <td className={styles.ledgerCell}>
                  <Badge severity={sev as "low" | "medium" | "high" | "critical"}>{sev}</Badge>
                </td>
                <td className={styles.ledgerCell}>
                  <Badge severity={row.reconciliationStatus === "MATCHED" ? "low" : row.reconciliationStatus.startsWith("MISSING") ? "high" : "medium"}>{row.reconciliationStatus}</Badge>
                </td>
                <td className={styles.ledgerCell}>
                  <code className={styles.ledgerCode}>{id}</code>
                </td>
                <td className={styles.ledgerCell}>
                  {row.internalStatus ? (
                    <Badge severity={row.internalStatus === "SETTLED" ? "low" : "medium"}>
                      {row.internalStatus}
                    </Badge>
                  ) : (
                    <Badge severity="high">MISSING</Badge>
                  )}
                </td>
                <td className={styles.ledgerCell}>
                  {row.partnerStatus ? (
                    <Badge severity={row.partnerStatus === "SETTLED" ? "low" : "medium"}>
                      {row.partnerStatus}
                    </Badge>
                  ) : (
                    <Badge severity="high">MISSING</Badge>
                  )}
                </td>
                <td className={styles.ledgerCell} style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                  {row.internalAmount != null ? `${row.internalAmount.toLocaleString()}` : "-"}
                </td>
                <td className={styles.ledgerCell} style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                  {row.partnerAmount != null ? `${row.partnerAmount.toLocaleString()}` : "-"}
                </td>
                <td className={`${styles.ledgerCell} ${styles.deltaCell}`} style={{ color: delta > 0 ? "#ef4444" : "var(--text-muted)" }}>
                  {delta > 0 ? (
                    <span className={styles.deltaBadge}>
                      <span>{`${delta.toLocaleString()}`}</span>
                      <span className={`${styles.diffBadge} ${deltaDirection > 0 ? styles.diffBadgeNegative : ""}`}>
                        {deltaDirection > 0 ? "▲" : "▼"}
                        {`${delta.toLocaleString()}`}
                      </span>
                    </span>
                  ) : "-"}
                </td>
                <td className={styles.ledgerCell} style={{ textAlign: "center" }}>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>

      <div className={styles.mobileCards}>
        {rows.map((row) => {
          const id = row.partnerTxnId || row.internalTxnId || row.id;
          const isChecked = Boolean(selectedRows[id]);
          const delta = row.delta ?? Math.abs(Number(row.internalAmount ?? 0) - Number(row.partnerAmount ?? 0));
          const sev = row.severity ?? (row.reconciliationStatus === "MATCHED" ? "low" : row.reconciliationStatus.startsWith("MISSING") ? "high" : "medium");
          return (
            <div
              key={`mobile-${id}`}
              onClick={() => onSelectRow(id)}
              className={`${styles.mobileCard} ${selectedRowId === id ? styles.mobileCardSelected : ""}`}
            >
              <div className={styles.mobileHeader}>
                <div className={styles.mobileHeaderLeft}>
                  {row.reconciliationStatus !== "MATCHED" && (
                    <input checked={isChecked} onChange={() => onToggleCheck(id)} onClick={(e) => e.stopPropagation()} type="checkbox" />
                  )}
                  <Badge severity={sev as "low" | "medium" | "high" | "critical"}>{sev}</Badge>
                  <code className={styles.ledgerCode} style={{ color: "#fff", overflow: "hidden", textOverflow: "ellipsis" }}>{id}</code>
                </div>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <Badge severity={row.reconciliationStatus === "MATCHED" ? "low" : row.reconciliationStatus.startsWith("MISSING") ? "high" : "medium"}>{row.reconciliationStatus}</Badge>
                <div style={{ fontSize: 13, fontWeight: 700, color: delta > 0 ? "#ef4444" : "var(--text-muted)" }}>
                  {delta > 0 ? `Δ ${delta.toLocaleString()}` : "No Delta"}
                </div>
              </div>
              <div className={styles.mobileCompare}>
                <div>
                  <div className={styles.compareLabel}>Internal</div>
                  <div>{row.internalStatus ? <Badge severity={row.internalStatus === "SETTLED" ? "low" : "medium"}>{row.internalStatus}</Badge> : <Badge severity="high">MISSING</Badge>}</div>
                  <div className={styles.compareAmount}>{row.internalAmount != null ? `${row.internalAmount.toLocaleString()}` : "-"}</div>
                </div>
                <div>
                  <div className={styles.compareLabel}>Partner</div>
                  <div>{row.partnerStatus ? <Badge severity={row.partnerStatus === "SETTLED" ? "low" : "medium"}>{row.partnerStatus}</Badge> : <Badge severity="high">MISSING</Badge>}</div>
                  <div className={styles.compareAmount}>{row.partnerAmount != null ? `${row.partnerAmount.toLocaleString()}` : "-"}</div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <PaginationBar
        total={total}
        limit={limit}
        offset={offset}
        onPageChange={onPageChange}
        onLimitChange={onLimitChange}
      />
    </div>
  );
}
