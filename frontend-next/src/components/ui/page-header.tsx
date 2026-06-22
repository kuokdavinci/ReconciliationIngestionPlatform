import styles from "./page-header.module.css";

export function PageHeader({ title, description }: { title: string; description?: string }) {
  return (
    <header className={styles.header}>
      <h1 className={styles.title}>{title}</h1>
      {description && <p className={styles.description}>{description}</p>}
    </header>
  );
}
