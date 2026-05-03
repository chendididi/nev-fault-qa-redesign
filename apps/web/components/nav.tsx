"use client";

import Link from "next/link";
import type { MouseEvent } from "react";
import { usePathname, useRouter } from "next/navigation";
import { BookOpen, Bot, LogOut, MessageSquare, Settings, Users } from "lucide-react";
import { clearToken } from "@/lib/api";

const links = [
  { href: "/chat", label: "诊断工作台", icon: MessageSquare },
  { href: "/admin/knowledge", label: "知识库", icon: BookOpen },
  { href: "/admin/models", label: "模型配置", icon: Settings },
  { href: "/admin/users", label: "用户", icon: Users },
];

type NavProps = {
  locked?: boolean;
  lockMessage?: string;
};

export function Nav({ locked = false, lockMessage = "当前任务正在处理中，请等待完成后再切换页面。" }: NavProps) {
  const pathname = usePathname();
  const router = useRouter();

  function blockNavigation(event: MouseEvent) {
    event.preventDefault();
    window.alert(lockMessage);
  }

  return (
    <aside className="glass-panel hidden h-[calc(100vh-48px)] w-64 shrink-0 flex-col p-4 md:flex">
      <div className="flex min-h-14 items-center gap-3 px-2 pb-4">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-line bg-[var(--floating-surface)] text-accent">
          <Bot className="h-5 w-5" />
        </span>
        <div>
          <div className="text-lg font-extrabold leading-tight text-ink">NEV Fault QA</div>
          <div className="text-xs text-[var(--text-secondary)]">维修诊断 RAG</div>
        </div>
      </div>
      <nav className="flex-1 space-y-2">
        {links.map((item) => {
          const active = pathname.startsWith(item.href);
          const disabled = locked && !active;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-disabled={disabled}
              onClick={disabled ? blockNavigation : undefined}
              className={`flex h-12 items-center gap-3 rounded-xl border px-3 text-sm font-semibold ${disabled ? "cursor-not-allowed opacity-55" : ""} ${active ? "border-[color-mix(in_srgb,var(--primary-color)_24%,transparent)] bg-[color-mix(in_srgb,var(--primary-color)_12%,var(--floating-surface))] text-ink" : "border-transparent text-ink hover:border-line hover:bg-[color-mix(in_srgb,var(--text-primary)_7%,transparent)]"}`}
            >
              <span className={`flex h-8 w-8 items-center justify-center rounded-lg border ${active ? "border-[color-mix(in_srgb,var(--primary-color)_28%,transparent)] bg-[color-mix(in_srgb,var(--primary-color)_14%,var(--bg-primary))] text-[var(--primary-active)]" : "border-line bg-[var(--bg-secondary)] text-ink"}`}>
                <Icon className="h-4 w-4" />
              </span>
              {item.label}
            </Link>
          );
        })}
      </nav>
      <button
        className="secondary-button flex h-11 items-center gap-3 rounded-xl px-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-55"
        disabled={locked}
        onClick={() => {
          if (locked) {
            window.alert(lockMessage);
            return;
          }
          clearToken();
          router.push("/login");
        }}
      >
        <LogOut className="h-4 w-4" />
        退出登录
      </button>
    </aside>
  );
}
