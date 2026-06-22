export interface ScheduleJob {
  partner: string;
  fetchMethod: string;
  schedule: string;
  destination: string;
  enabled: boolean;
  status: string;
  statusMessage?: string;
  hasPendingFile?: boolean;
  pendingReviewPackets?: number;
  latestRuntimeRun?: { date?: string };
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
