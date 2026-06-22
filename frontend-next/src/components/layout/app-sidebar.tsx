"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import styles from "./app-sidebar.module.css";

const navItems = [
  { href: "/review-center", label: "Review Center" },
  { href: "/reconciliation", label: "Reconciliation" },
  { href: "/schedules", label: "Schedules" },
  { href: "/audit-log", label: "Audit Log" },
];

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <aside className={styles.sidebar}>
      <div className={styles.brand}>
        <div className={styles.brandMark}>
          <span className="material-symbols-outlined" style={{ fontSize: 20 }}>sync</span>
        </div>
        <div>
          <strong className={styles.brandName}>Adapter</strong>
          <span className={styles.brandSubtitle}>Dashboard</span>
        </div>
      </div>

      <nav className={styles.nav}>
        {navItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`${styles.navItem} ${pathname === item.href ? styles.navItemActive : ""}`}
          >
            {item.label}
          </Link>
        ))}
      </nav>

      <div className={styles.footer}>
        <div className={styles.statusDot} />
        <span className={styles.statusText}>System Online</span>
      </div>
    </aside>
  );
}
