import { get, post } from "./client";
import type { ScheduleJob } from "@/types/schedules";

export interface AutomationJobsResponse {
  jobs: ScheduleJob[];
}

export interface RunJobResponse {
  ok: boolean;
  queued: boolean;
  actor: string;
  partner: string;
  message: string;
  runtimeRunId: string;
}

export async function listJobs() {
  return get<AutomationJobsResponse>("/automation/jobs");
}

export async function getJob(partner: string) {
  const response = await listJobs();
  return response.jobs.find((job) => job.partner === partner) ?? null;
}

export async function runJob(partner: string) {
  return post<RunJobResponse>(`/automation/jobs/${partner}/run`);
}
