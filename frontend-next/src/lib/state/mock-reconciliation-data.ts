import type { ReconciliationRun, ReconciliationStats, ReconciliationRow, InsightItem } from "@/types/reconciliation";

export const mockRunStatus: ReconciliationRun = {
  status: "COMPLETED",
  startedAt: "2026-06-10T10:00:00Z",
  completedAt: "2026-06-10T10:42:00Z",
  totalRows: 1284,
  matchedRows: 1220,
  unmatchedRows: 64,
  missingPartnerRows: 28,
  missingInternalRows: 36,
};

export const mockStats: ReconciliationStats = {
  total: 1284,
  matched: 1220,
  unmatched: 64,
  missingPartner: 28,
  missingInternal: 36,
  matchRate: 95.0,
};

const statuses = ["MATCHED", "AMOUNT_MISMATCH", "MISSING_PARTNER", "MISSING_INTERNAL", "STATUS_MISMATCH"];

export function generateMockRows(count: number): ReconciliationRow[] {
  const rows: ReconciliationRow[] = [];
  for (let i = 0; i < count; i++) {
    const status = statuses[i % statuses.length];
    const internalAmt = Math.round(Math.random() * 1000000);
    const partnerAmt = status === "MATCHED" ? internalAmt : Math.round(Math.random() * 1000000);
    rows.push({
      id: `row_${i}`,
      partnerTxnId: status === "MISSING_INTERNAL" ? undefined : `PARTNER_TXN_${1000 + i}`,
      internalTxnId: status === "MISSING_PARTNER" ? undefined : `INT_TXN_${2000 + i}`,
      reconciliationStatus: status,
      internalStatus: status.startsWith("MISSING") ? "MISSING" : "SETTLED",
      partnerStatus: status.startsWith("MISSING") ? "MISSING" : "SETTLED",
      internalAmount: internalAmt,
      partnerAmount: partnerAmt,
      delta: Math.abs(internalAmt - partnerAmt),
      severity: status === "MATCHED" ? "LOW" : status === "MISSING_PARTNER" || status === "MISSING_INTERNAL" ? "HIGH" : "MEDIUM",
    });
  }
  return rows;
}

export const mockInsights: InsightItem[] = [
  {
    id: "insight_1",
    category: "ANOMALY",
    severity: "HIGH",
    title: "Amount mismatch",
    shortSummary: "Consistent delta suggests a fee or commission configuration issue.",
    affectedCount: 28,
    partner: "MOMO",
    confidence: 0.86,
    metrics: [
      { label: "delta each", value: "5,000 VND" },
      { label: "sample share", value: "10.0%" },
      { label: "partner", value: "MOMO" },
    ],
    evidence: {
      affectedRecords: 2,
      deltaPerRecord: "5,000 VND",
      totalObservedDelta: "10,000 VND",
      patternType: "Consistent amount difference",
      partner: "MOMO",
      sampleCoverage: "10.0%",
    },
    likelyCause: "Fee or commission calculation may be applied differently between internal records and partner settlement data.",
    recommendation: {
      action: "Review MOMO fee and commission rules for affected transactions.",
      why: "Both records share the same fixed amount delta.",
      owner: "Finance Operations",
      priority: "HIGH",
      expectedOutcome: "Confirm whether the delta is expected fee behavior or a real settlement discrepancy.",
    },
    impact: {
      currentImpact: "10,000 VND observed mismatch across 2 records.",
      potentialImpact: "Repeated mismatches may appear in future MOMO settlement batches if the configuration is unchanged.",
      isEstimated: true,
    },
    samples: [
      {
        transactionId: "TXN001",
        internalAmount: 259200,
        partnerAmount: 254200,
        delta: 5000,
        status: "MISMATCH",
        timestamp: "2026-06-18 10:21",
      },
    ],
  },
  {
    id: "insight_2",
    category: "PATTERN",
    severity: "MEDIUM",
    title: "High-value mismatch cluster",
    shortSummary: "High-value transactions are mismatching more often than the rest of the sample.",
    affectedCount: 42,
    partner: "MOMO",
    metrics: [
      { label: "records", value: "42" },
      { label: "share", value: "18.4%" },
      { label: "band", value: ">500k" },
    ],
    evidence: {
      patternType: "High-value mismatch cluster",
      affectedRecords: 42,
      sampleCoverage: "18.4%",
      partner: "MOMO",
    },
    likelyCause: "Higher-value rows may be using a different commission tier or post-processing rule.",
    recommendation: {
      action: "Review high-value commission and settlement rules.",
      why: "The mismatch rate increases once transaction amount crosses the same threshold.",
      owner: "Reconciliation Operator",
      priority: "MEDIUM",
      expectedOutcome: "Determine whether the threshold behavior is expected or a configuration drift.",
    },
  },
  {
    id: "insight_3",
    category: "RECOMMENDATION",
    severity: "LOW",
    title: "Open review packet",
    shortSummary: "A targeted review packet can clear the repeated status mismatch set faster.",
    affectedCount: 12,
    partner: "MOMO",
    metrics: [
      { label: "eligible rows", value: "12" },
      { label: "status", value: "SETTLED" },
    ],
    evidence: {
      affectedRecords: 12,
      partner: "MOMO",
      patternType: "Repeated status mismatch",
    },
    recommendation: {
      action: "Create a review task for the repeated status mismatch packet.",
      why: "The affected rows share the same status pattern and can be reviewed as one unit.",
      owner: "Operations",
      priority: "LOW",
      expectedOutcome: "Clear the review queue without manually checking each row.",
    },
  },
];
