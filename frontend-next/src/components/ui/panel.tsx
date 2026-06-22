import styles from "./panel.module.css";

interface PanelProps {
  children: React.ReactNode;
  className?: string;
  header?: React.ReactNode;
}

export function Panel({ children, className, header }: PanelProps) {
  return (
    <div className={`${styles.panel} ${className ?? ""}`}>
      {header && <div className={styles.header}>{header}</div>}
      {children}
    </div>
  );
}
