"use client";

import { useRef } from "react";
import { Button } from "@/components/ui/button";
import type { StudioWizardState } from "@/types/mapping";
import styles from "./mapping-studio.module.css";

interface Props {
  wizard: StudioWizardState;
  onExcelUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onJsonUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onManualSetup: () => void;
}

export function MappingStudioUploadStep({ wizard, onExcelUpload, onJsonUpload, onManualSetup }: Props) {
  const excelInputRef = useRef<HTMLInputElement>(null);
  const jsonInputRef = useRef<HTMLInputElement>(null);

  return (
    <div className={styles.uploadGrid}>
      <div className={`${styles.optionCard} ${styles.optionCardPrimary}`}>
        {wizard.loading ? (
          <div className={styles.centerSpinner}>
            <div className="spinner" style={{ marginBottom: 16 }} />
            <p style={{ fontSize: 13, fontWeight: 600, color: "var(--brand-primary)", margin: 0 }}>
              AI is analyzing your file...
            </p>
            <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
              Mapping structure extraction in progress
            </p>
          </div>
        ) : (
          <div>
            <div style={{ fontSize: 48, color: "var(--brand-primary)", marginBottom: 12 }}>🧠</div>
            <h3 className={styles.optionCardTitle}>Upload Partner Sample</h3>
            <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 16 }}>
              Upload a spreadsheet (.xlsx, .xls, .csv) to generate a draft mapping.
            </p>
          </div>
        )}
        <div>
          <input
            ref={excelInputRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            style={{ display: "none" }}
            onChange={onExcelUpload}
          />
          <Button
            variant="primary"
            style={{ width: "100%" }}
            disabled={wizard.loading}
            onClick={() => excelInputRef.current?.click()}
          >
            {wizard.loading ? "Processing..." : "Generate Draft"}
          </Button>
        </div>
      </div>

      <div className={styles.optionCard}>
        <div>
          <div style={{ fontSize: 48, color: "var(--text-muted)", marginBottom: 12 }}>📄</div>
          <h3 className={styles.optionCardTitle}>Upload Existing Schema</h3>
          <p className={styles.optionCardDesc}>
            Start from an existing JSON schema and send a revised version for review.
          </p>
        </div>
        <div>
          <input
            ref={jsonInputRef}
            type="file"
            accept=".json"
            style={{ display: "none" }}
            onChange={onJsonUpload}
          />
          <Button
            variant="default"
            style={{ width: "100%" }}
            onClick={() => jsonInputRef.current?.click()}
          >
            Browse JSON File
          </Button>
        </div>
      </div>

      <div className={styles.optionCard}>
        <div>
          <div style={{ fontSize: 48, color: "var(--text-muted)", marginBottom: 12 }}>✏️</div>
          <h3 className={styles.optionCardTitle}>Manual Setup</h3>
          <p className={styles.optionCardDesc}>
            Start configuration manually by pasting JSON mapping template.
          </p>
        </div>
        <div>
          <Button
            variant="default"
            style={{ width: "100%" }}
            onClick={onManualSetup}
          >
            Paste Schema JSON
          </Button>
        </div>
      </div>
    </div>
  );
}
