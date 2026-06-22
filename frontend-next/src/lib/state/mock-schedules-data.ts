import type { ScheduleJob } from "@/types/schedules";

export const mockScheduleJobs: ScheduleJob[] = [
  {
    partner: "MOMO",
    fetchMethod: "SFTP",
    schedule: "0 8 * * *",
    destination: "MOMO_SETTLEMENT",
    enabled: true,
    status: "HEALTHY",
    statusMessage: "Last run completed successfully.",
    pendingReviewPackets: 5,
    hasPendingFile: false,
  },
  {
    partner: "ZALOPAY",
    fetchMethod: "SFTP",
    schedule: "0 6,18 * * *",
    destination: "ZALOPAY_DAILY",
    enabled: true,
    status: "HEALTHY",
    statusMessage: "Waiting for next scheduled run.",
    pendingReviewPackets: 2,
    hasPendingFile: true,
  },
  {
    partner: "SHOPEE",
    fetchMethod: "API",
    schedule: "0 7 * * 1-5",
    destination: "SHOPEE_WEEKDAY",
    enabled: false,
    status: "DISABLED",
    statusMessage: "Disabled by operator.",
    pendingReviewPackets: 0,
  },
  {
    partner: "GRAB",
    fetchMethod: "SFTP",
    schedule: "0 9 * * *",
    destination: "GRAB_DAILY",
    enabled: true,
    status: "HEALTHY",
    statusMessage: "No active runtime work.",
    pendingReviewPackets: 0,
  },
];

export const mockRecentPackets = [
  {
    _id: "auto_1",
    partner: "MOMO",
    fileName: "MOMO_SETTLEMENT_20260610.xlsx",
    fetchMethod: "SFTP",
    status: "PENDING",
    riskSummary: { severity: "medium" },
    recommendedAction: { reason: "Routine format-drift check completed. No anomalies detected." },
  },
  {
    _id: "auto_2",
    partner: "ZALOPAY",
    fileName: "ZALOPAY_DAILY_20260609.xlsx",
    fetchMethod: "SFTP",
    status: "PENDING",
    riskSummary: { severity: "low" },
    recommendedAction: { reason: "New file detected with standard format." },
  },
];
