"use client";

import { FormEvent, useEffect, useState } from "react";
import { PlugZap, Save } from "lucide-react";
import { AppShell } from "@/components/shell";
import { api } from "@/lib/api";

const initial = {
  base_url: "http://127.0.0.1:8317/v1",
  api_key: "",
  chat_model: "gpt-5.5",
  embedding_model: "BAAI/bge-m3",
  vision_model: "",
  rerank_model: "BAAI/bge-reranker-v2-m3",
  embedding_dim: 1024,
};

type ModelCheck = {
  name: "chat" | "vision_ocr" | "embedding" | "rerank";
  ok: boolean;
  message: string;
};

export default function ModelPage() {
  const [form, setForm] = useState(initial);
  const [message, setMessage] = useState("");
  const [checks, setChecks] = useState<ModelCheck[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api<Partial<typeof initial>>("/api/admin/model-config").then((data) => {
      setForm((prev) => ({...prev, ...data, api_key: data.api_key?.includes("...") ? "" : data.api_key || prev.api_key}));
    }).catch(() => undefined);
  }, []);

  function update(key: keyof typeof initial, value: string | number) {
    setForm((prev) => ({...prev, [key]: value}));
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setMessage("");
    try {
      await api("/api/admin/model-config", {method: "PUT", body: JSON.stringify(form)});
      setMessage("配置已保存");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "保存失败");
    } finally {
      setLoading(false);
    }
  }

  async function test() {
    setChecks([]);
    setMessage("测试中...");
    setLoading(true);
    try {
      const data = await api<{ok: boolean; checks: ModelCheck[]}>("/api/admin/model-config/test", {method: "POST", body: JSON.stringify(form)});
      setChecks(data.checks);
      setMessage(data.ok ? "所有模型检查通过" : "部分模型检查失败");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "测试失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AppShell>
      <div className="max-w-4xl p-6">
        <header className="mb-5">
          <h1 className="text-xl font-semibold">模型配置</h1>
          <p className="mt-1 text-sm text-slate-500">使用 OpenAI-compatible 协议统一接入第三方 API 或本地 Ollama/vLLM/LM Studio。</p>
        </header>
        <form onSubmit={save} className="space-y-4 rounded-md border border-line bg-white p-5">
          {([
            ["base_url", "Base URL"],
            ["api_key", "API Key"],
            ["chat_model", "对话模型"],
            ["embedding_model", "本地 Embedding 模型"],
            ["vision_model", "视觉模型（留空复用对话模型）"],
            ["rerank_model", "本地 Rerank 模型"],
          ] as const).map(([key, label]) => (
            <label key={key} className="block text-sm">
              <span className="mb-2 block text-slate-700">{label}</span>
              <input className="h-10 w-full rounded-md border border-line px-3" value={form[key]} onChange={(e) => update(key, e.target.value)} />
            </label>
          ))}
          <label className="block text-sm">
            <span className="mb-2 block text-slate-700">Embedding 维度</span>
            <input className="h-10 w-full rounded-md border border-line px-3" type="number" value={form.embedding_dim} onChange={(e) => update("embedding_dim", Number(e.target.value))} />
          </label>
          {message && <div className="rounded-md border border-line bg-panel p-3 text-sm">{message}</div>}
          {checks.length > 0 && (
            <div className="space-y-2 rounded-md border border-line bg-panel p-3">
              {checks.map((check) => (
                <div key={check.name} className="flex gap-3 text-sm">
                  <span className={check.ok ? "text-emerald-700" : "text-red-700"}>{check.ok ? "通过" : "失败"}</span>
                  <span className="w-28 shrink-0 font-medium">{check.name}</span>
                  <span className="min-w-0 break-words text-slate-700">{check.message}</span>
                </div>
              ))}
            </div>
          )}
          <div className="flex gap-3">
            <button disabled={loading} className="flex h-10 items-center gap-2 rounded-md bg-accent px-4 text-sm font-semibold text-white disabled:opacity-60">
              <Save className="h-4 w-4" />
              保存配置
            </button>
            <button type="button" disabled={loading} onClick={test} className="flex h-10 items-center gap-2 rounded-md border border-line bg-white px-4 text-sm disabled:opacity-60">
              <PlugZap className="h-4 w-4" />
              测试连接
            </button>
          </div>
        </form>
      </div>
    </AppShell>
  );
}
