export interface ReconciliationRun {
  status: string;
  startedAt: string;
  completedAt?: string;
  totalRows: number;
  matchedRows: number;
  unmatchedRows: number;
  missingPartnerRows: number;
  missingInternalRows: number;
}

export interface ReconciliationStats {
  total: number;
  matched: number;
  unmatched: number;
  missingPartner: number;
  missingInternal: number;
  matchRate: number;
  reviewedCount?: number;
  totalReviewable?: number;
}

export interface ReviewNote {
  time: string;
  event: string;
}

export interface ReviewRecord {
  _id: string;
  partner: string;
  date: string;
  recordKey: string;
  reviewed: boolean;
  resolvedStatus?: string;
  notes: ReviewNote[];
  createdAt: string;
  updatedAt: string;
}

export interface ReconciliationRow {
  id: string;
  partnerTxnId?: string;
  internalTxnId?: string;
  reconciliationStatus: string;
  internalStatus?: string;
  partnerStatus?: string;
  internalAmount?: number;
  partnerAmount?: number;
  delta?: number;
  severity?: string;
  reviewState?: ReviewRecord;
}

export interface InsightItem {
  id: string;
  category: string;
  severity: string;
  title: string;
  shortSummary: string;
  affectedCount: number;
  partner?: string;
  confidence?: number;
  metrics?: { label: string; value: string }[];
  likelyCause?: string;
  recommendation?: {
    action: string;
    why?: string;
    owner?: string;
    priority?: string;
    expectedOutcome?: string;
  };
  impact?: {
    currentImpact?: string;
    potentialImpact?: string;
    isEstimated?: boolean;
  };
  evidence?: Record<string, unknown>;
  samples?: Array<Record<string, unknown>>;
}

export interface ReconciliationPageState {
  partner: string;
  date: string;
  reconStatus: string;
  filters: {
    amountMin: string;
    amountMax: string;
    dateFrom: string;
    dateTo: string;
  };
  pagination: {
    limit: number;
    offset: number;
  };
  runStatus: ReconciliationRun | null;
  stats: ReconciliationStats | null;
  results: ReconciliationRow[];
  insights: {
    anomalies: InsightItem[] | null;
    patterns: InsightItem[] | null;
    recommendations: InsightItem[] | null;
  };
  selectedRows: Record<string, boolean>;
  selectedEvidenceRowId: string | null;
  explainItem: InsightItem | null;
  loading: boolean;
}
