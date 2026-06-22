import styles from "./badge.module.css";

type Severity = "neutral" | "critical" | "high" | "medium" | "low";
type Shape = "default" | "pill";

interface BadgeProps {
  children: React.ReactNode;
  severity?: Severity;
  shape?: Shape;
  className?: string;
}

export function Badge({ children, severity = "neutral", shape = "default", className }: BadgeProps) {
  const cls = [
    styles.badge,
    styles[severity],
    shape === "pill" ? styles.pill : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  return <span className={cls}>{children}</span>;
}
