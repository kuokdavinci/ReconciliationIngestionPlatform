import styles from "./page-section.module.css";

export function PageSection({ children, className }: { children: React.ReactNode; className?: string }) {
  return <section className={`${styles.section} ${className ?? ""}`}>{children}</section>;
}
