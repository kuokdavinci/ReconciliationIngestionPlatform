"use client";

import styles from "./reconciliation.module.css";

interface Props {
  total: number;
  limit: number;
  offset: number;
  onPageChange: (offset: number) => void;
  onLimitChange: (limit: number) => void;
}

export function PaginationBar({ total, limit, offset, onPageChange, onLimitChange }: Props) {
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const currentPage = Math.floor(offset / limit) + 1;
  const pageStart = total ? offset + 1 : 0;
  const pageEnd = Math.min(offset + limit, total);

  return (
    <div className={styles.paginationBar}>
      <div className={styles.paginationSummary}>
        Showing <strong>{pageStart}</strong>-<strong>{pageEnd}</strong> of <strong>{total}</strong> records
        <span style={{ marginLeft: 8 }}>Page <strong>{currentPage}</strong> of <strong>{totalPages}</strong></span>
      </div>

      <div className={styles.paginationSection}>
        <span className={styles.paginationLabel}>Page size</span>
        <select
          value={limit}
          onChange={(e) => onLimitChange(Number(e.target.value))}
          className={styles.toolbarControlSmall}
        >
          {[25, 50, 100].map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
      </div>

      <div className={styles.paginationSection}>
        <button
          disabled={currentPage <= 1}
          onClick={() => onPageChange(offset - limit)}
          className={styles.paginationButton}
        >
          ‹
        </button>
        <button
          disabled={currentPage >= totalPages}
          onClick={() => onPageChange(offset + limit)}
          className={styles.paginationButton}
        >
          ›
        </button>
      </div>
    </div>
  );
}
