export interface ScheduleJob {
  partner: string;
  fetchMethod: string;
  schedule: string;
  destination: string;
  enabled: boolean;
  status: string;
  statusMessage?: string;
  duplicateOutcome?: "FILE_DUPLICATE" | "FETCH_UNIT_REPLAY" | "NO_NEW_FILE";
  duplicateMessage?: string | null;
  hasPendingFile?: boolean;
  pendingReviewPackets?: number;
  latestRuntimeRun?: { date?: string; stats?: Record<string, unknown>; message?: string };
  recentPackets?: RecentPacket[];
}

export interface RecentPacket {
  _id: string;
  partner: string;
  fileName: string;
  fetchMethod: string;
  status: string;
  createdAt?: string;
  decisionMode?: string | null;
  sourceType?: string;
  riskSummary?: { severity: string };
  recommendedAction?: { reason: string };
  reviewedAt?: string;
  reviewedBy?: string;
}
