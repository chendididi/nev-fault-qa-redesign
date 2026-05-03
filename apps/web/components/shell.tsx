import { Nav } from "@/components/nav";

type AppShellProps = {
  children: React.ReactNode;
  navigationLocked?: boolean;
  navigationLockMessage?: string;
};

export function AppShell({ children, navigationLocked = false, navigationLockMessage }: AppShellProps) {
  return (
    <div className="app-shell">
      <Nav locked={navigationLocked} lockMessage={navigationLockMessage} />
      <main className="app-content">{children}</main>
    </div>
  );
}
