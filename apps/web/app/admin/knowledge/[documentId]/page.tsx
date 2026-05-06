"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Clock3,
  Database,
  FileText,
  Layers3,
  LoaderCircle,
  MessageSquareText,
  RefreshCcw,
  Search,
  ShieldAlert,
} from "lucide-react";
import { AppShell } from "@/components/shell";
import { api } from "@/lib/api";

type TraceEvent = {
  id?: string;
  name?: string;
  step: string;
  label: string;
  status: string;
  duration_ms?: number | null;
  summary?: Record<string, unknown>;
  preview?: string;
  error?: string;
};

type MetadataCoverage = Record<string, {count: number; ratio: number}>;

type ChunkPreview = {
  id: string;
  chunk_index?: number;
  metadata: Record<string, unknown>;
  has_embedding: boolean;
  char_count: number;
  preview: string;
};

type RagTrace = {
  document: {
    id: string;
    title: string;
    filename: string;
    content_type: string;
    status: string;
    error?: string;
    knowledge_base: string;
  };
  events: TraceEvent[];
  chunk_summary: {
    total_chunks: number;
    embedded_chunks: number;
    min_chars: number;
    max_chars: number;
    avg_chars: number;
    metadata_coverage: MetadataCoverage;
  };
  chunk_previews: ChunkPreview[];
};

type DemoHit = {
  rank: number;
  id: string;
  title: string;
  filename: string;
  chunk_index?: number;
  score: number;
  vector_score: number;
  keyword_score: number;
  pre_score: number;
  rerank_score?: number | null;
  sources: string[];
  keyword_matches: string[];
  metadata: Record<string, unknown>;
  content: string;
};

type RagDemo = {
  query: {question: string; retrieval_terms: string[]};
  steps: TraceEvent[];
  candidates: DemoHit[];
  reranked_hits: DemoHit[];
  prompt_summary: Record<string, unknown>;
  answer: string;
  citations: Array<{label: string; title: string; filename: string; metadata: Record<string, unknown>; content: string}>;
  fallbacks: Array<{stage: string; message: string; used: string}>;
};

const timelineSteps = [
  ["upload_saved", "文件已保存"],
  ["queued", "入库任务排队"],
  ["extract_text_ocr", "文本抽取/OCR"],
  ["chunk", "文本切片"],
  ["embedding", "向量化"],
  ["index", "写入索引"],
  ["ready", "入库完成"],
];

const demoQuestion = "车辆无法快充，仪表提示充电系统异常，应该优先检查哪些部件？";

export default function KnowledgeDetailPage() {
  const params = useParams();
  const documentId = String(params.documentId || "");
  const [trace, setTrace] = useState<RagTrace | null>(null);
  const [demo, setDemo] = useState<RagDemo | null>(null);
  const [question, setQuestion] = useState(demoQuestion);
  const [loading, setLoading] = useState(true);
  const [demoLoading, setDemoLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadTrace() {
    const data = await api<RagTrace>(`/api/admin/documents/${documentId}/rag-trace`);
    setTrace(data);
    return data;
  }

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function loadLoop() {
      try {
        const data = await loadTrace();
        if (stopped) return;
        setError("");
        setLoading(false);
        if (!["ready", "failed"].includes(data.document.status)) {
          timer = setTimeout(loadLoop, 2500);
        }
      } catch (err) {
        if (!stopped) {
          setError(err instanceof Error ? err.message : "加载失败");
          setLoading(false);
        }
      }
    }

    if (documentId) void loadLoop();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [documentId]);

  const timeline = useMemo(() => {
    const byStep = new Map((trace?.events || []).map((event) => [event.step, event]));
    const items = timelineSteps.map(([step, label]) => byStep.get(step) || {step, label, status: "pending"});
    const failed = (trace?.events || []).find((event) => event.step === "failed");
    return failed && !items.some((item) => item.step === "failed") ? [...items, failed] : items;
  }, [trace]);

  async function runDemo(event: FormEvent) {
    event.preventDefault();
    setDemoLoading(true);
    setError("");
    try {
      const data = await api<RagDemo>(`/api/admin/documents/${documentId}/rag-demo`, {
        method: "POST",
        body: JSON.stringify({question}),
      });
      setDemo(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "演示检索失败");
    } finally {
      setDemoLoading(false);
    }
  }

  if (loading) {
    return (
      <AppShell adminScrollable>
        <div className="flex h-full items-center justify-center text-sm text-slate-500">
          <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
          正在加载 RAG trace
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell adminScrollable>
      <div className="space-y-5 p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <Link href="/admin/knowledge" className="mb-3 inline-flex items-center gap-2 text-sm text-slate-500 hover:text-ink">
              <ArrowLeft className="h-4 w-4" />
              返回知识库
            </Link>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="max-w-3xl truncate text-2xl font-semibold">{trace?.document.title || "文档 RAG 流程"}</h1>
              {trace && <StatusBadge status={trace.document.status} />}
            </div>
            <p className="mt-1 text-sm text-slate-500">{trace?.document.filename} · {trace?.document.knowledge_base}</p>
          </div>
          <button
            className="inline-flex h-10 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-semibold"
            onClick={() => void loadTrace()}
          >
            <RefreshCcw className="h-4 w-4" />
            刷新
          </button>
        </div>

        {error && <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
        {trace?.document.error && <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{trace.document.error}</div>}

        <section className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)_420px]">
          <aside className="surface-card p-4">
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold">
              <Clock3 className="h-4 w-4" />
              入库时间线
            </div>
            <div className="space-y-3">
              {timeline.map((event) => (
                <TimelineItem key={event.step} event={event} />
              ))}
            </div>
          </aside>

          <main className="space-y-4">
            <section className="surface-card p-4">
              <div className="mb-4 flex items-center gap-2 text-sm font-semibold">
                <Layers3 className="h-4 w-4" />
                Chunk 与 metadata 覆盖
              </div>
              <div className="grid gap-3 sm:grid-cols-4">
                <Metric label="Chunk" value={trace?.chunk_summary.total_chunks ?? 0} />
                <Metric label="已向量化" value={trace?.chunk_summary.embedded_chunks ?? 0} />
                <Metric label="平均字符" value={trace?.chunk_summary.avg_chars ?? 0} />
                <Metric label="最长字符" value={trace?.chunk_summary.max_chars ?? 0} />
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(trace?.chunk_summary.metadata_coverage || {}).map(([key, value]) => (
                  <div key={key} className="rounded-md border border-line bg-white p-3">
                    <div className="flex items-center justify-between text-xs text-slate-500">
                      <span>{key}</span>
                      <span>{value.count}/{trace?.chunk_summary.total_chunks || 0}</span>
                    </div>
                    <ScoreBar value={value.ratio} />
                  </div>
                ))}
              </div>
            </section>

            <section className="surface-card p-4">
              <div className="mb-4 flex items-center gap-2 text-sm font-semibold">
                <FileText className="h-4 w-4" />
                Chunk 预览
              </div>
              <div className="space-y-3">
                {(trace?.chunk_previews || []).map((chunk) => (
                  <div key={chunk.id} className="rounded-md border border-line bg-white p-3">
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <span>#{chunk.chunk_index ?? "-"}</span>
                      <span>{chunk.char_count} chars</span>
                      <span className={chunk.has_embedding ? "text-emerald-700" : "text-amber-700"}>
                        {chunk.has_embedding ? "embedding ready" : "keyword fallback"}
                      </span>
                      {metadataLabel(chunk.metadata)}
                    </div>
                    <p className="text-sm leading-6 text-slate-700">{chunk.preview}</p>
                  </div>
                ))}
                {!trace?.chunk_previews.length && <div className="text-sm text-slate-500">暂无 chunk，等待 worker 入库。</div>}
              </div>
            </section>
          </main>

          <aside className="space-y-4">
            <section className="surface-card p-4">
              <div className="mb-4 flex items-center gap-2 text-sm font-semibold">
                <MessageSquareText className="h-4 w-4" />
                答辩演示问题
              </div>
              <form onSubmit={runDemo} className="space-y-3">
                <textarea
                  className="min-h-24 w-full rounded-md border border-line p-3 text-sm leading-6"
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                />
                <button
                  className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-md bg-accent px-4 text-sm font-semibold text-white disabled:opacity-60"
                  disabled={demoLoading || !question.trim()}
                >
                  {demoLoading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                  运行文档级 RAG
                </button>
              </form>
            </section>

            {demo && (
              <>
                <section className="surface-card p-4">
                  <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
                    <Database className="h-4 w-4" />
                    检索与生成步骤
                  </div>
                  <div className="space-y-2">
                    {demo.steps.map((step) => (
                      <TimelineItem key={step.name || step.step} event={{...step, step: step.name || step.step}} compact />
                    ))}
                  </div>
                  {!!demo.fallbacks.length && (
                    <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
                      <div className="mb-1 flex items-center gap-1 font-semibold">
                        <ShieldAlert className="h-3.5 w-3.5" />
                        演示兜底已启用
                      </div>
                      {demo.fallbacks.map((item, index) => (
                        <div key={`${item.stage}-${index}`}>{item.stage}: {item.used}</div>
                      ))}
                    </div>
                  )}
                </section>

                <section className="surface-card p-4">
                  <div className="mb-3 text-sm font-semibold">TopK 排名</div>
                  <div className="space-y-3">
                    {demo.reranked_hits.map((hit) => (
                      <HitRow key={hit.id} hit={hit} />
                    ))}
                    {!demo.reranked_hits.length && <div className="text-sm text-slate-500">没有检索到可引用 chunk。</div>}
                  </div>
                </section>

                <section className="surface-card p-4">
                  <div className="mb-3 text-sm font-semibold">最终答案与引用</div>
                  <div className="whitespace-pre-wrap rounded-md border border-line bg-white p-3 text-sm leading-6 text-slate-800">{demo.answer}</div>
                  <div className="mt-3 space-y-2">
                    {demo.citations.map((citation) => (
                      <div key={citation.label} className="rounded-md border border-line bg-white p-3 text-xs text-slate-600">
                        <div className="mb-1 font-semibold text-ink">{citation.label} {citation.title}</div>
                        <div>{citation.filename}</div>
                        <div className="mt-1 leading-5">{citation.content}</div>
                      </div>
                    ))}
                  </div>
                </section>
              </>
            )}
          </aside>
        </section>
      </div>
    </AppShell>
  );
}

function TimelineItem({event, compact = false}: {event: TraceEvent; compact?: boolean}) {
  const tone = statusTone(event.status);
  const Icon = event.status === "running" ? LoaderCircle : event.status === "done" ? CheckCircle2 : event.status === "failed" || event.status === "fallback" ? AlertTriangle : Clock3;
  return (
    <div className={`rounded-md border ${tone.border} ${tone.bg} ${compact ? "p-2" : "p-3"}`}>
      <div className="flex items-start gap-2">
        <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${tone.text} ${event.status === "running" ? "animate-spin" : ""}`} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-sm font-semibold">{event.label}</span>
            {typeof event.duration_ms === "number" && <span className="shrink-0 text-xs text-slate-500">{event.duration_ms} ms</span>}
          </div>
          {event.preview && !compact && <p className="mt-2 line-clamp-3 text-xs leading-5 text-slate-600">{event.preview}</p>}
          {event.error && <p className="mt-1 text-xs leading-5 text-red-700">{event.error}</p>}
        </div>
      </div>
    </div>
  );
}

function Metric({label, value}: {label: string; value: number}) {
  return (
    <div className="rounded-md border border-line bg-white p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
    </div>
  );
}

function HitRow({hit}: {hit: DemoHit}) {
  return (
    <div className="rounded-md border border-line bg-white p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="min-w-0 truncate text-sm font-semibold">#{hit.rank} Chunk {hit.chunk_index ?? "-"}</div>
        <span className="text-xs text-slate-500">{scoreText(hit.score)}</span>
      </div>
      <ScoreBar value={normalizeScore(hit.score)} />
      <div className="mt-2 flex flex-wrap gap-1 text-[11px] text-slate-500">
        <span>vector {scoreText(hit.vector_score)}</span>
        <span>pre {scoreText(hit.pre_score)}</span>
        {hit.rerank_score !== null && hit.rerank_score !== undefined && <span>rerank {scoreText(hit.rerank_score)}</span>}
        {hit.sources.map((source) => <span key={source} className="rounded bg-slate-100 px-1.5 py-0.5">{source}</span>)}
      </div>
      <p className="mt-2 text-xs leading-5 text-slate-600">{hit.content}</p>
    </div>
  );
}

function ScoreBar({value}: {value: number}) {
  const width = Math.max(4, Math.min(100, Math.round(value * 100)));
  return (
    <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
      <div className="h-full rounded-full bg-accent" style={{width: `${width}%`}} />
    </div>
  );
}

function StatusBadge({status}: {status: string}) {
  const tone = statusTone(status);
  return <span className={`rounded-md border px-2.5 py-1 text-xs font-semibold ${tone.border} ${tone.bg} ${tone.text}`}>{statusLabel(status)}</span>;
}

function statusTone(status: string) {
  if (status === "done" || status === "ready") return {border: "border-emerald-200", bg: "bg-emerald-50", text: "text-emerald-700"};
  if (status === "running" || status === "processing") return {border: "border-blue-200", bg: "bg-blue-50", text: "text-blue-700"};
  if (status === "failed") return {border: "border-red-200", bg: "bg-red-50", text: "text-red-700"};
  if (status === "fallback") return {border: "border-amber-200", bg: "bg-amber-50", text: "text-amber-700"};
  return {border: "border-line", bg: "bg-white", text: "text-slate-500"};
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: "排队中",
    processing: "处理中",
    ready: "已完成",
    failed: "失败",
    running: "运行中",
    done: "完成",
    fallback: "兜底",
  };
  return labels[status] || status;
}

function normalizeScore(value: number) {
  if (!Number.isFinite(value)) return 0;
  if (value >= 0 && value <= 1) return value;
  return Math.max(0, Math.min(1, value / 100));
}

function scoreText(value: number) {
  return Number.isFinite(value) ? value.toFixed(3) : "-";
}

function metadataLabel(metadata: Record<string, unknown>) {
  const system = metadataValue(metadata.system);
  const dtc = metadataValue(metadata.dtc);
  const label = [system, dtc].filter(Boolean).join(" · ");
  return label ? <span>{label}</span> : null;
}

function metadataValue(value: unknown) {
  if (Array.isArray(value)) return value.map(String).join("/");
  if (typeof value === "string" || typeof value === "number") return String(value);
  return "";
}
