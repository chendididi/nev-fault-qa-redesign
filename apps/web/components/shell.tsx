import { Nav } from "@/components/nav";

type AppShellProps = {
  children: React.ReactNode;
  navigationLocked?: boolean;
  navigationLockMessage?: string;
  contentScrollable?: boolean;
  pageScrollable?: boolean;
};

export function AppShell({
  children,
  navigationLocked = false,
  navigationLockMessage,
  contentScrollable = false,
  pageScrollable = false,
}: AppShellProps) {
  return (
    <div className={`app-shell ${pageScrollable ? "app-shell-scrollable" : ""}`}>
      <Nav locked={navigationLocked} lockMessage={navigationLockMessage} />
      <main className={`app-content ${contentScrollable ? "app-content-scrollable" : ""}`}>{children}</main>
    </div>
  );
}
