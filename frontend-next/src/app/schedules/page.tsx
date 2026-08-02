"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { Topbar } from "@/components/layout/topbar";
import { PageSection } from "@/components/ui/page-section";
import { Panel } from "@/components/ui/panel";
import { MetricCard } from "@/components/ui/metric-card";
import { ScheduleTable } from "@/components/schedules/schedule-table";
import { RecentPacketsGrid } from "@/components/schedules/recent-packets-grid";
import { useToast } from "@/components/ui/toast";
import * as api from "@/lib/api/automation";
import type { RecentPacket, ScheduleJob } from "@/types/schedules";
import polish from "@/components/ui/dashboard-polish.module.css";

export default function SchedulesPage() {
  const [jobs, setJobs] = useState<ScheduleJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [runningPartners, setRunningPartners] = useState<Record<string, boolean>>({});
  const { showToast } = useToast();

  const loadJobs = useCallback(async () => {
    try {
      const response = await api.listJobs();
      setJobs(response.jobs ?? []);
      return response.jobs ?? [];
    } catch {
      showToast("Failed to load schedules from backend", "error");
      setJobs([]);
      return [];
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  const enabledJobs = jobs.filter((j) => j.enabled);
  const pendingReview = jobs.reduce((sum, j) => sum + ((j.pendingReviewPackets as number) ?? 0), 0);
  const partnersWaiting = jobs.filter((j) => j.hasPendingFile).length;
  const activeRuns = jobs.filter((j) => j.status === "HEALTHY").length;

  // Active status list that indicates a background process is running
  const hasActiveJobRunning = useMemo(() => {
    const activeStatuses = ["QUEUED", "FETCHING", "INGESTING", "RECONCILING", "RUNNING"];
    return jobs.some((j) => activeStatuses.includes(j.status));
  }, [jobs]);

  useEffect(() => {
    let cancelled = false;

    async function bootstrapJobs() {
      try {
        const response = await api.listJobs();
        if (cancelled) return;
        setJobs(response.jobs ?? []);
      } catch {
        if (cancelled) return;
        showToast("Failed to load schedules from backend", "error");
        setJobs([]);
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void bootstrapJobs();

    // Set up polling if there's any active job running
    let intervalId: NodeJS.Timeout | null = null;
    if (hasActiveJobRunning) {
      intervalId = setInterval(() => {
        void loadJobs();
      }, 3000);
    }

    return () => {
      cancelled = true;
      if (intervalId) clearInterval(intervalId);
    };
  }, [hasActiveJobRunning, loadJobs, showToast]);

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

  const handleRunJob = async (partner: string) => {
    try {
      setRunningPartners((prev) => ({ ...prev, [partner]: true }));
      const res = await api.runJob(partner);
      showToast(res.message || `Triggered run for ${partner}`, "success");
      await loadJobs();
      window.setTimeout(() => {
        void loadJobs().finally(() => {
          setRunningPartners((prev) => ({ ...prev, [partner]: false }));
        });
      }, 1800);
    } catch {
      setRunningPartners((prev) => ({ ...prev, [partner]: false }));
      showToast(`Failed to trigger run for ${partner}`, "error");
    }
  };

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
            <span className={polish.panelIcon}>
              <span className="material-symbols-outlined" style={{ fontSize: 18 }}>schedule</span>
            </span>
          </div>
        }>
          <ScheduleTable
            jobs={jobs}
            onRunJob={handleRunJob}
            runningPartners={runningPartners}
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
    </div>
  );
}
