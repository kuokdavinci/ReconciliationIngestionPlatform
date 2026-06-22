import styles from "./metric-card.module.css";

interface MetricCardProps {
  label: string;
  value: string | number;
  subtitle?: string;
  className?: string;
}

export function MetricCard({ label, value, subtitle, className }: MetricCardProps) {
  return (
    <div className={`${styles.card} ${className ?? ""}`}>
      <span className={styles.label}>{label}</span>
      <strong className={styles.value}>{value}</strong>
      {subtitle && <small className={styles.subtitle}>{subtitle}</small>}
    </div>
  );
}
