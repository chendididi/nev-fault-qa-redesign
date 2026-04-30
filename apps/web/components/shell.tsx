import { Nav } from "@/components/nav";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-shell">
      <Nav />
      <main className="app-content">{children}</main>
    </div>
  );
}
