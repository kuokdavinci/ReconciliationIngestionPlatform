"use client";

import { Suspense, useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Topbar } from "@/components/layout/topbar";
import { PageSection } from "@/components/ui/page-section";
import { Panel } from "@/components/ui/panel";
import { MetricCard } from "@/components/ui/metric-card";
import { ScheduleTable } from "@/components/schedules/schedule-table";
import { RecentPacketsGrid } from "@/components/schedules/recent-packets-grid";
import { RecoveryDetailsPanel } from "@/components/schedules/recovery-details-panel";
import { BackfillDialog } from "@/components/schedules/backfill-dialog";
import { BackfillProgressPanel } from "@/components/schedules/backfill-progress-panel";
import { isActiveRuntimeStatus } from "@/components/schedules/recovery-status";
import { useToast } from "@/components/ui/toast";
import * as api from "@/lib/api/automation";
import type { RecentPacket, RecoveryStatus, ScheduleJob } from "@/types/schedules";
import polish from "@/components/ui/dashboard-polish.module.css";

const RECOVERY_FILTER_OPTIONS = [
  { value: "ALL", label: "All recovery states" },
  { value: "FAILED", label: "Failed" },
  { value: "BLOCKED", label: "Blocked" },
  { value: "WAITING_REVIEW", label: "Waiting review" },
  { value: "PROCESSING", label: "Processing" },
  { value: "COMPLETED", label: "Completed" },
] as const;

const ALL_PARTNERS = "ALL";

type RecoveryFilter = (typeof RECOVERY_FILTER_OPTIONS)[number]["value"];

function parseRecoveryFilter(value: string | null): RecoveryFilter {
  return RECOVERY_FILTER_OPTIONS.some((option) => option.value === value)
    ? (value as RecoveryFilter)
    : "ALL";
}

export default function SchedulesPage() {
  return (
    <Suspense fallback={<SchedulesLoading />}>
      <SchedulesContent />
    </Suspense>
  );
}

function SchedulesLoading() {
  return (
    <div>
      <Topbar title="Schedules" subtitle="Automation schedules and recurring tasks" />
      <PageSection><div className={polish.emptyBlock}>Loading schedules...</div></PageSection>
    </div>
  );
}

function SchedulesContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [jobs, setJobs] = useState<ScheduleJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [runningPartners, setRunningPartners] = useState<Record<string, boolean>>({});
  const [selectedRecoveryPartner, setSelectedRecoveryPartner] = useState<string | null>(() => searchParams.get("runtimePartner"));
  const [retryingRecoveryPartner, setRetryingRecoveryPartner] = useState<string | null>(null);
  const [resolvingRecovery, setResolvingRecovery] = useState(false);
  const [backfillPartner, setBackfillPartner] = useState<string | null>(null);
  const [backfillRunId, setBackfillRunId] = useState<string | null>(() => searchParams.get("backfillRunId"));
  const [startingBackfill, setStartingBackfill] = useState(false);
  const runtimePollRef = useRef<number | null>(null);
  const { showToast } = useToast();

  const loadJobs = useCallback(async () => {
    try {
      const response = await api.listJobs();
      setJobs(response.jobs ?? []);
      return response.jobs ?? [];
    } catch {
      showToast("Failed to load schedules from backend", "error");
      return [];
    } finally {
      setLoading(false);
    }
  }, [showToast]);
  const loadJobsRef = useRef(loadJobs);
  useEffect(() => {
    loadJobsRef.current = loadJobs;
  }, [loadJobs]);

  const selectedRecoveryJob = useMemo(
    () => jobs.find((job) => job.partner === selectedRecoveryPartner) ?? null,
    [jobs, selectedRecoveryPartner],
  );
  const recoveryFilter = parseRecoveryFilter(searchParams.get("recovery"));
  const partnerFilter = searchParams.get("partner") || ALL_PARTNERS;
  const partnerOptions = useMemo(
    () => [ALL_PARTNERS, ...jobs.map((job) => job.partner).sort()],
    [jobs],
  );
  const filteredJobs = useMemo(
    () => jobs.filter((job) => (
      (partnerFilter === ALL_PARTNERS || job.partner === partnerFilter)
      && (recoveryFilter === "ALL" || job.recovery?.status === recoveryFilter)
    )),
    [jobs, partnerFilter, recoveryFilter],
  );

  const enabledJobs = jobs.filter((j) => j.enabled);
  const pendingReview = jobs.reduce((sum, j) => sum + ((j.pendingReviewPackets as number) ?? 0), 0);
  const partnersWaiting = jobs.filter((j) => j.hasPendingFile).length;
  const activeRuns = jobs.filter((j) => isActiveRuntimeStatus(j.status)).length;
  const recoveryOverview = useMemo(() => ({
    failed: jobs.filter((job) => job.recovery?.status === "FAILED").length,
    blocked: jobs.filter((job) => job.recovery?.status === "BLOCKED").length,
    waitingReview: jobs.filter((job) => job.recovery?.status === "WAITING_REVIEW").length,
  }), [jobs]);

  // Active status list that indicates a background process is running
  const hasActiveJobRunning = useMemo(() => {
    return jobs.some((j) => isActiveRuntimeStatus(j.status));
  }, [jobs]);

  useEffect(() => {
    const loadTimer = window.setTimeout(() => {
      void loadJobsRef.current();
    }, 0);
    // Set up polling if there's any active job running
    let intervalId: NodeJS.Timeout | null = null;
    if (hasActiveJobRunning) {
      intervalId = setInterval(() => {
        void loadJobsRef.current();
      }, 3000);
    }

    return () => {
      window.clearTimeout(loadTimer);
      if (intervalId) clearInterval(intervalId);
    };
  }, [hasActiveJobRunning]);

  useEffect(() => {
    return () => {
      if (runtimePollRef.current) clearTimeout(runtimePollRef.current);
    };
  }, []);

  const recentPackets = useMemo<RecentPacket[]>(() => {
    return jobs
      .flatMap((j) => (j.recentPackets ?? []).map((packet) => ({
        ...packet,
        partner: packet.partner || j.partner || "-",
        fetchMethod: packet.fetchMethod || j.fetchMethod || "-",
      })))
      .sort((a, b) => String(b.createdAt || b.reviewedAt || "").localeCompare(String(a.createdAt || a.reviewedAt || "")))
      .slice(0, 8);
  }, [jobs]);

  const pollRuntimeRun = useCallback((
    partner: string,
    runtimeRunId: string,
    onSettled: () => void,
    attemptsLeft = 15,
  ) => {
    const poll = async (remaining: number) => {
      const refreshedJobs = await loadJobs();
      const job = refreshedJobs.find((item) => item.partner === partner);
      const latestRun = job?.latestRuntimeRun;
      const latestRunId = latestRun?.id || latestRun?._id;
      const terminal = latestRunId === runtimeRunId
        && (
          latestRun?.status === "COMPLETED"
          || latestRun?.status === "FAILED"
          || latestRun?.status === "WAITING_REVIEW"
        );

      if (terminal || remaining <= 1) {
        runtimePollRef.current = null;
        onSettled();
        return;
      }

      runtimePollRef.current = window.setTimeout(() => {
        void poll(remaining - 1);
      }, 1000);
    };

    void poll(attemptsLeft);
  }, [loadJobs]);

  const handleRunJob = async (partner: string) => {
    try {
      setRunningPartners((prev) => ({ ...prev, [partner]: true }));
      const res = await api.runJob(partner);
      showToast(res.message || `Triggered run for ${partner}`, "success");
      await loadJobs();
      pollRuntimeRun(partner, res.runtimeRunId, () => {
        setRunningPartners((prev) => ({ ...prev, [partner]: false }));
      });
    } catch {
      setRunningPartners((prev) => ({ ...prev, [partner]: false }));
      showToast(`Failed to trigger run for ${partner}`, "error");
    }
  };

  const handleRetryRecovery = async (partnerOverride?: string) => {
    const partner = partnerOverride || selectedRecoveryPartner;
    if (!partner || retryingRecoveryPartner) return;

    setRetryingRecoveryPartner(partner);
    let queued = false;
    try {
      const response = await api.retryRecovery(partner);
      showToast(response.message || `Recovery retry queued for ${partner}`, "success");
      await loadJobs();
      queued = true;
      pollRuntimeRun(partner, response.runtimeRunId, () => {
        setRetryingRecoveryPartner(null);
      });
    } catch (error) {
      const refreshedJobs = await loadJobs();
      const refreshedJob = refreshedJobs.find((item) => item.partner === partner);
      const alreadyCompleted = refreshedJob?.latestRuntimeRun?.status === "COMPLETED"
        && refreshedJob.recovery?.status === "COMPLETED";
      const message = error instanceof Error ? error.message : "Unknown recovery retry error";
      showToast(
        alreadyCompleted
          ? "Recovery had already completed; status refreshed."
          : `Recovery retry failed: ${message}`,
        alreadyCompleted ? "success" : "error",
      );
    } finally {
      if (!queued) setRetryingRecoveryPartner(null);
    }
  };

  const handleStartBackfill = async (fromDate: string, toDate: string) => {
    if (!backfillPartner || startingBackfill) return;
    setStartingBackfill(true);
    try {
      const response = await api.startBackfill(backfillPartner, { fromDate, toDate });
      setBackfillRunId(response._id);
      setBackfillPartner(null);
      showToast(`Backfill queued for ${backfillPartner}`, "success");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to start backfill.";
      showToast(message, "error");
    } finally {
      setStartingBackfill(false);
    }
  };

  const handleResolveRecovery = async (action: "RETRY" | "SKIP", reason: string) => {
    const partner = selectedRecoveryPartner;
    if (!partner || !reason || resolvingRecovery) return;

    setResolvingRecovery(true);
    try {
      const response = await api.resolveRecovery(partner, action, reason);
      showToast(response.message, "success");
      await loadJobs();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown recovery resolution error";
      showToast(`Recovery resolution failed: ${message}`, "error");
    } finally {
      setResolvingRecovery(false);
    }
  };

  const handleRecoveryFilterChange = useCallback((value: RecoveryFilter) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value === "ALL") params.delete("recovery");
    else params.set("recovery", value as RecoveryStatus);
    const query = params.toString();
    router.replace(query ? `/schedules?${query}` : "/schedules", { scroll: false });
  }, [router, searchParams]);

  const handlePartnerFilterChange = useCallback((value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value === ALL_PARTNERS) params.delete("partner");
    else params.set("partner", value);
    const query = params.toString();
    router.replace(query ? `/schedules?${query}` : "/schedules", { scroll: false });
  }, [router, searchParams]);

  if (loading) {
    return (
      <div>
        <Topbar title="Schedules" subtitle="Automation schedules and recurring tasks" />
        <PageSection><div className={polish.emptyBlock}>Loading schedules...</div></PageSection>
      </div>
    );
  }

  return (
    <div>
      <Topbar
        title="Schedules"
        subtitle="Automation schedules, partner fetch routes, and recent review output."
        actions={
          <div className={polish.toolbar}>
            <span className={polish.toolbarLabel}>Operators view</span>
            <div className={polish.statChip}>
              {jobs.length} configured partners
            </div>
          </div>
        }
      />

      <PageSection>
        <div className={polish.sectionGrid}>
          <MetricCard label="Enabled Jobs" value={enabledJobs.length} subtitle="Scheduler-connected fetch configs" />
          <MetricCard label="Pending Review" value={pendingReview} subtitle="Review items waiting after runs" />
          <MetricCard label="Partners Waiting" value={partnersWaiting} subtitle="Files ready but not reconciled" />
          <MetricCard label="Active Runs" value={activeRuns} subtitle="Currently healthy routes" />
          <MetricCard label="Partners Covered" value={jobs.length} subtitle="Configured partner fetch routes" />
          <MetricCard label="Failed Recovery" value={recoveryOverview.failed} subtitle="Retryable or failed streams" />
          <MetricCard label="Blocked Recovery" value={recoveryOverview.blocked} subtitle="Needs operator resolution" />
          <MetricCard label="Waiting Review" value={recoveryOverview.waitingReview} subtitle="Mapping/config review required" />
        </div>
      </PageSection>

      <PageSection>
        <Panel header={
          <div className={polish.panelHeader}>
            <div>
              <strong className={polish.panelTitle}>Scheduler Jobs</strong>
              <p className={polish.panelDescription}>
                Realtime visibility into partner fetch routes, pending files, and current runtime stages.
              </p>
            </div>
            <div className={polish.toolbar}>
              <div className={polish.toolbarField}>
                <label htmlFor="partner-filter" className={polish.toolbarLabel}>Partner</label>
                <select
                  id="partner-filter"
                  className={polish.toolbarControl}
                  value={partnerOptions.includes(partnerFilter) ? partnerFilter : ALL_PARTNERS}
                  onChange={(event) => handlePartnerFilterChange(event.target.value)}
                >
                  <option value={ALL_PARTNERS}>All partners</option>
                  {partnerOptions.filter((partner) => partner !== ALL_PARTNERS).map((partner) => (
                    <option key={partner} value={partner}>{partner}</option>
                  ))}
                </select>
              </div>
              <div className={polish.toolbarField}>
                <label htmlFor="recovery-status-filter" className={polish.toolbarLabel}>Recovery status</label>
                <select
                  id="recovery-status-filter"
                  className={polish.toolbarControl}
                  value={recoveryFilter}
                  onChange={(event) => handleRecoveryFilterChange(parseRecoveryFilter(event.target.value))}
                >
                  {RECOVERY_FILTER_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </div>
              <span className={polish.panelIcon}>
                <span className="material-symbols-outlined" style={{ fontSize: 18 }}>schedule</span>
              </span>
            </div>
          </div>
        }>
            <ScheduleTable
              jobs={filteredJobs}
              onRunJob={handleRunJob}
              onBackfill={(partner) => setBackfillPartner(partner)}
              onRetryRecovery={(partner) => { void handleRetryRecovery(partner); }}
              onViewRecovery={(job) => setSelectedRecoveryPartner(job.partner)}
              runningPartners={runningPartners}
              retryingRecoveryPartners={retryingRecoveryPartner ? { [retryingRecoveryPartner]: true } : {}}
              emptyMessage={recoveryFilter === "ALL" ? undefined : "No partner matches this recovery status."}
            />
        </Panel>
      </PageSection>

      <PageSection>
        <Panel header={
          <div className={polish.panelHeader}>
            <div>
              <strong className={polish.panelTitle}>Recent Automation Review Output</strong>
              <p className={polish.panelDescription}>
                Latest packets generated by automation-backed file fetches and format-drift checks.
              </p>
            </div>
            <span className={polish.panelIcon}>
              <span className="material-symbols-outlined" style={{ fontSize: 18 }}>smart_toy</span>
            </span>
          </div>
        }>
          <RecentPacketsGrid packets={recentPackets} />
        </Panel>
      </PageSection>

      <RecoveryDetailsPanel
        job={selectedRecoveryJob}
        onClose={() => setSelectedRecoveryPartner(null)}
        onRefresh={() => { void loadJobs(); }}
        onRetry={() => { void handleRetryRecovery(); }}
        retrying={retryingRecoveryPartner === selectedRecoveryPartner}
        onResolve={(action, reason) => { void handleResolveRecovery(action, reason); }}
        resolving={resolvingRecovery}
      />

      <BackfillDialog
        partner={backfillPartner}
        open={Boolean(backfillPartner)}
        submitting={startingBackfill}
        onClose={() => { if (!startingBackfill) setBackfillPartner(null); }}
        onSubmit={handleStartBackfill}
      />
      <BackfillProgressPanel
        runId={backfillRunId}
        onClose={() => setBackfillRunId(null)}
      />
    </div>
  );
}
