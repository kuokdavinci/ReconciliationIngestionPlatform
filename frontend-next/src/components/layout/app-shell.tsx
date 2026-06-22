import { AppSidebar } from "./app-sidebar";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-shell" style={{ minHeight: "100vh", display: "grid", gridTemplateColumns: "280px minmax(0, 1fr)" }}>
      <AppSidebar />
      <main className="app-main" style={{ display: "flex", flexDirection: "column" }}>
        {children}
      </main>
    </div>
  );
}
