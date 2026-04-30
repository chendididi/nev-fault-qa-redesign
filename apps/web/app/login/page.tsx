"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { Bot } from "lucide-react";
import { API_BASE, setToken } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("admin@example.com");
  const [password, setPassword] = useState("Admin123!");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/auth/login`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({email, password}),
      });
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      setToken(data.access_token);
      router.push("/chat");
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="grid min-h-screen grid-cols-1 bg-[var(--bg-secondary)] lg:grid-cols-[1fr_460px]">
      <section className="relative hidden items-center justify-end overflow-hidden bg-black px-10 py-12 lg:flex">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(255,255,255,0.08),transparent_34%)]" />
        <div className="relative flex flex-col items-end">
          <span className="animate-[brandFadeIn_0.8s_ease-out_forwards] text-right text-[13vw] font-black uppercase leading-[0.84] tracking-normal text-white opacity-0">NEV</span>
          <span className="animate-[brandFadeIn_0.8s_ease-out_0.2s_forwards] text-right text-[13vw] font-black uppercase leading-[0.84] tracking-normal text-white opacity-0">FAULT</span>
          <span className="animate-[brandFadeIn_0.8s_ease-out_0.4s_forwards] text-right text-[13vw] font-black uppercase leading-[0.84] tracking-normal text-white opacity-0">QA</span>
        </div>
      </section>
      <section className="flex items-center justify-center px-6 py-12">
        <form onSubmit={submit} className="surface-card w-full max-w-[420px] space-y-6 p-8">
          <div className="flex flex-col items-center gap-4 text-center">
            <span className="flex h-20 w-20 items-center justify-center rounded-xl border-[3px] border-line bg-[var(--floating-surface)] shadow-[var(--shadow-lg)]">
              <Bot className="h-9 w-9 text-accent" />
            </span>
            <div>
              <h1 className="text-2xl font-extrabold text-ink">NEV Fault QA</h1>
              <p className="mt-2 text-sm text-[var(--text-secondary)]">新能源汽车维修多模态 RAG 系统</p>
            </div>
          </div>

          <div className="rounded-lg border border-dashed border-line bg-[var(--bg-secondary)] p-4 text-sm">
            <div className="text-[var(--text-secondary)]">默认管理员</div>
            <div className="mt-1 break-all font-bold text-ink">admin@example.com / Admin123!</div>
          </div>

          <label className="block text-sm">
            <span className="mb-2 block font-semibold text-ink">邮箱</span>
            <input className="focus-ring h-11 w-full rounded-lg border border-line px-3" value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="block text-sm">
            <span className="mb-2 block font-semibold text-ink">密码</span>
            <input className="focus-ring h-11 w-full rounded-lg border border-line px-3" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          {error && <div className="rounded-lg border border-[color-mix(in_srgb,var(--warning-color)_40%,transparent)] bg-[color-mix(in_srgb,var(--warning-color)_10%,transparent)] p-3 text-sm text-[var(--warning-color)]">{error}</div>}
          <button disabled={loading} className="primary-button h-11 w-full rounded-lg px-4 text-sm font-bold disabled:opacity-60">
            {loading ? "登录中..." : "进入系统"}
          </button>
        </form>
      </section>
    </main>
  );
}
