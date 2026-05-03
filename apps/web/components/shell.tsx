import { Nav } from "@/components/nav";

type AppShellProps = {
  children: React.ReactNode;
  navigationLocked?: boolean;
  navigationLockMessage?: string;
  contentScrollable?: boolean;
  pageScrollable?: boolean;
  adminScrollable?: boolean;
};

export function AppShell({
  children,
  navigationLocked = false,
  navigationLockMessage,
  contentScrollable = false,
  pageScrollable = false,
  adminScrollable = false,
}: AppShellProps) {
  return (
    <div className={`app-shell ${pageScrollable ? "app-shell-scrollable" : ""} ${adminScrollable ? "app-shell-admin-scroll" : ""}`}>
      <Nav locked={navigationLocked} lockMessage={navigationLockMessage} />
      <main className={`app-content ${contentScrollable || adminScrollable ? "app-content-scrollable" : ""}`}>{children}</main>
    </div>
  );
}
