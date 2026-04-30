"use client";

import { FormEvent, useEffect, useState } from "react";
import { RefreshCcw, Trash2, Upload } from "lucide-react";
import { AppShell } from "@/components/shell";
import { api } from "@/lib/api";

type KB = { id: string; name: string; description: string };
type Doc = { id: string; title: string; filename: string; status: string; error?: string; knowledge_base: string; created_at: string };

export default function KnowledgePage() {
  const [kbs, setKbs] = useState<KB[]>([]);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [kbId, setKbId] = useState("");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");

  async function load() {
    const [kbData, docData] = await Promise.all([
      api<{items: KB[]}>("/api/knowledge-bases"),
      api<{items: Doc[]}>("/api/admin/documents"),
    ]);
    setKbs(kbData.items);
    setDocs(docData.items);
    if (!kbId && kbData.items[0]) setKbId(kbData.items[0].id);
  }

  useEffect(() => {
    let active = true;
    async function loadInitial() {
      try {
        const [kbData, docData] = await Promise.all([
          api<{items: KB[]}>("/api/knowledge-bases"),
          api<{items: Doc[]}>("/api/admin/documents"),
        ]);
        if (!active) return;
        setKbs(kbData.items);
        setDocs(docData.items);
        if (kbData.items[0]) setKbId(kbData.items[0].id);
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "加载失败");
      }
    }
    void loadInitial();
    return () => {
      active = false;
    };
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.set("knowledge_base_id", kbId);
    form.set("title", title || file.name);
    form.set("file", file);
    await api("/api/admin/documents", {method: "POST", body: form});
    setTitle("");
    setFile(null);
    await load();
  }

  return (
    <AppShell>
      <div className="p-6">
        <header className="mb-5">
          <h1 className="text-xl font-semibold">知识库管理</h1>
          <p className="mt-1 text-sm text-slate-500">上传维修手册、故障案例、表格和图片资料，worker 会自动解析、切片和向量化。</p>
        </header>
        {error && <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
        <form onSubmit={submit} className="mb-6 grid gap-3 rounded-md border border-line bg-white p-4 md:grid-cols-[220px_1fr_1fr_auto]">
          <select className="h-10 rounded-md border border-line px-3 text-sm" value={kbId} onChange={(e) => setKbId(e.target.value)}>
            {kbs.map((kb) => <option key={kb.id} value={kb.id}>{kb.name}</option>)}
          </select>
          <input className="h-10 rounded-md border border-line px-3 text-sm" placeholder="资料标题" value={title} onChange={(e) => setTitle(e.target.value)} />
          <input className="h-10 rounded-md border border-line px-3 text-sm" type="file" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          <button className="flex h-10 items-center justify-center gap-2 rounded-md bg-accent px-4 text-sm font-semibold text-white">
            <Upload className="h-4 w-4" />
            上传
          </button>
        </form>
        <div className="overflow-hidden rounded-md border border-line bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-panel text-xs text-slate-500">
              <tr>
                <th className="px-4 py-3">标题</th>
                <th className="px-4 py-3">文件</th>
                <th className="px-4 py-3">知识库</th>
                <th className="px-4 py-3">状态</th>
                <th className="px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {docs.map((doc) => (
                <tr key={doc.id} className="border-t border-line">
                  <td className="px-4 py-3 font-medium">{doc.title}</td>
                  <td className="px-4 py-3 text-slate-600">{doc.filename}</td>
                  <td className="px-4 py-3 text-slate-600">{doc.knowledge_base}</td>
                  <td className="px-4 py-3">
                    <span className="rounded bg-slate-100 px-2 py-1 text-xs">{doc.status}</span>
                    {doc.error && <div className="mt-1 text-xs text-red-600">{doc.error}</div>}
                  </td>
                  <td className="flex gap-2 px-4 py-3">
                    <button title="重建索引" className="rounded-md border border-line p-2" onClick={() => api(`/api/admin/documents/${doc.id}/reingest`, {method: "POST"}).then(load)}>
                      <RefreshCcw className="h-4 w-4" />
                    </button>
                    <button title="删除" className="rounded-md border border-line p-2" onClick={() => api(`/api/admin/documents/${doc.id}`, {method: "DELETE"}).then(load)}>
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </AppShell>
  );
}
