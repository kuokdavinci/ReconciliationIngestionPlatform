"use client";

import { useState, useMemo, useEffect, useCallback } from "react";
import { Topbar } from "@/components/layout/topbar";
import { PageSection } from "@/components/ui/page-section";
import { Panel } from "@/components/ui/panel";
import { AuditTable } from "@/components/audit/audit-table";
import { AuditDetailDialog } from "@/components/audit/audit-detail-dialog";
import { useToast } from "@/components/ui/toast";
import * as api from "@/lib/api/audit";
import polish from "@/components/ui/dashboard-polish.module.css";

const entityOptions = ["", "REVIEW_PACKET", "MAPPING_CONFIG", "RECONCILIATION_RUN"];
const actionOptions = ["", "APPROVED", "REJECTED", "APPROVE_ACTIVATE_NEXT_RUNTIME", "COMPLETED", "FAILED"];

export default function AuditLogPage() {
  const [events, setEvents] = useState<Record<string, unknown>[]>([]);
  const [entityFilter, setEntityFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const { showToast } = useToast();

  const loadEvents = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.listAuditEvents({ limit: 200 });
      setEvents(r.events ?? []);
    } catch {
      showToast("Failed to load audit events from backend", "error");
      setEvents([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void loadEvents();
    });
  }, [loadEvents]);

  const filtered = useMemo(() => {
    return events.filter((e) => {
      if (entityFilter && e.entityType !== entityFilter) return false;
      if (actionFilter && e.action !== actionFilter) return false;
      return true;
    });
  }, [events, entityFilter, actionFilter]);

  const selectedEvent = events.find((e) => (e._id ?? e.id) === selectedId) ?? null;

  return (
    <div>
      <Topbar
        title="Audit Log"
        subtitle="System activity, review decisions, and runtime changes across the platform."
        actions={
          <div className={polish.toolbar}>
            <div className={polish.toolbarField}>
              <span className={polish.toolbarLabel}>Entity</span>
              <select
                value={entityFilter}
                onChange={(e) => setEntityFilter(e.target.value)}
                className={polish.toolbarControl}
              >
                {entityOptions.map((o) => (
                  <option key={o} value={o}>{o || "All entities"}</option>
                ))}
              </select>
            </div>
            <div className={polish.toolbarField}>
              <span className={polish.toolbarLabel}>Action</span>
              <select
                value={actionFilter}
                onChange={(e) => setActionFilter(e.target.value)}
                className={`${polish.toolbarControl} ${polish.toolbarControlWide}`}
              >
                {actionOptions.map((o) => (
                  <option key={o} value={o}>{o || "All actions"}</option>
                ))}
              </select>
            </div>
          </div>
        }
      />

      <PageSection>
        <Panel header={
          <div className={polish.panelHeader}>
            <div>
              <strong className={polish.panelTitle}>Audit Log</strong>
              <p className={polish.panelDescription}>
                Read-only timeline for mapping approvals, review decisions, and reconciliation runs.
              </p>
            </div>
            <div className={polish.panelHeaderCompact}>
              <span className={polish.panelMeta}>{filtered.length} events</span>
              <span className={polish.panelIcon}>
                <span className="material-symbols-outlined" style={{ fontSize: 18 }}>history</span>
              </span>
            </div>
          </div>
        }>
          <div className={polish.toolbar} style={{ marginBottom: 16, justifyContent: "flex-end" }}>
            <div className={polish.toolbarField}>
              <span className={polish.toolbarLabel}>Matched Events</span>
              <div className={polish.statChip} style={{ height: 44 }}>
                {loading ? "..." : filtered.length}
              </div>
            </div>
          </div>

          {loading ? (
            <div className={polish.emptyBlock}>Loading audit events...</div>
          ) : (
            <AuditTable events={filtered as never} onSelect={setSelectedId} />
          )}
        </Panel>
      </PageSection>

      <AuditDetailDialog
        event={selectedEvent as never}
        open={!!selectedId}
        onClose={() => setSelectedId(null)}
      />
    </div>
  );
}
