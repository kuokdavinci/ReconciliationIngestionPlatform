"use client";

import { Button } from "@/components/ui/button";

interface Props {
  selectedCount: number;
  onApprove: () => void;
  onFlag: () => void;
  onClear: () => void;
}

export function BulkActionBar({ selectedCount, onApprove, onFlag, onClear }: Props) {
  if (selectedCount === 0) return null;

  return (
    <div style={{
      position: "fixed",
      left: "50%",
      bottom: 24,
      transform: "translateX(-50%)",
      background: "rgba(18, 22, 26, 0.95)",
      border: "1px solid var(--brand-primary)",
      boxShadow: "0 20px 40px rgba(0,0,0,0.6)",
      padding: "12px 24px",
      borderRadius: 12,
      display: "flex",
      alignItems: "center",
      gap: 16,
      zIndex: 1000,
      backdropFilter: "blur(12px)",
    }}>
      <span style={{ fontSize: 14, fontWeight: 600 }}>
        {selectedCount} items selected
      </span>
      <Button variant="primary" onClick={onApprove}>
        Apply Action
      </Button>
      <Button variant="tertiary" onClick={onFlag}>
        Mark Reviewed
      </Button>
      <Button variant="secondary" onClick={onClear}>
        Clear
      </Button>
    </div>
  );
}
