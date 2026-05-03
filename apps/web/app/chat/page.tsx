"use client";

import { FormEvent, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { BrainCircuit, FileSearch, History, ImagePlus, ListChecks, MessageSquarePlus, Plus, Search, Send, ShieldCheck, Sparkles, Trash2, type LucideIcon } from "lucide-react";
import { AppShell } from "@/components/shell";
import { ApiError, api } from "@/lib/api";
import { clearChatTask, getChatTaskSnapshot, startChatTask, subscribeChatTask, type ChatMessage as Message, type Citation } from "@/lib/background-tasks";

type KB = { id: string; name: string };
type ApiMessage = { role: "user" | "assistant" | "system"; content: string; citations?: Citation[] };
type Conversation = {
  id: string;
  title: string;
  last_message?: string;
  message_count: number;
  updated_at: string;
};
type PendingStep = { label: string; icon: LucideIcon };

const textPendingSteps: PendingStep[] = [
  {label: "正在检索知识库", icon: Search},
  {label: "正在分析故障现象", icon: BrainCircuit},
  {label: "正在组织诊断步骤", icon: Sparkles}
];

const imagePendingSteps: PendingStep[] = [
  {label: "正在识别图片内容", icon: ImagePlus},
  ...textPendingSteps
];

export default function ChatPage() {
  const [kbs, setKbs] = useState<KB[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [sessionId, setSessionId] = useState("");
  const [knowledgeBaseId, setKnowledgeBaseId] = useState("");
  const [question, setQuestion] = useState("车辆无法快充，仪表提示充电系统故障，应该如何排查？");
  const [image, setImage] = useState<File | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [deletingSessionId, setDeletingSessionId] = useState("");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const chatTask = useSyncExternalStore(subscribeChatTask, getChatTaskSnapshot, getChatTaskSnapshot);
  const loading = chatTask.status === "running";
  const pendingHasImage = chatTask.pendingHasImage;
  const handledCompletionRef = useRef<number | null>(null);

  useEffect(() => {
    api<{items: KB[]}>("/api/knowledge-bases").then((data) => {
      setKbs(data.items);
      if (data.items[0]) setKnowledgeBaseId(data.items[0].id);
    }).catch(() => undefined);
    loadConversations();
  }, []);

  useEffect(() => {
    if (chatTask.status === "idle" || chatTask.messages.length === 0) return;
    setMessages(chatTask.messages);
    setSessionId(chatTask.sessionId);
    if (chatTask.completedAt && handledCompletionRef.current !== chatTask.completedAt) {
      handledCompletionRef.current = chatTask.completedAt;
      void loadConversations();
    }
  }, [chatTask]);

  useEffect(() => {
    if (!loading) {
      setElapsedSeconds(0);
      return;
    }

    const startedAt = chatTask.startedAt || Date.now();
    const updateElapsed = () => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    };
    updateElapsed();
    const timer = window.setInterval(updateElapsed, 250);

    return () => window.clearInterval(timer);
  }, [loading, chatTask.startedAt]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({behavior: "smooth", block: "end"});
  }, [messages.length, loading]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text || loading) return;
    const started = startChatTask({
      question: text,
      knowledgeBaseId,
      sessionId,
      image,
      messages,
    });
    if (started) {
      setQuestion("");
      setImage(null);
    }
  }

  async function loadConversations() {
    try {
      const data = await api<{items: Conversation[]}>("/api/chat/sessions");
      setConversations(data.items);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return;
    }
  }

  async function loadConversation(id: string) {
    if (loading || id === sessionId) return;
    setHistoryLoading(true);
    try {
      const data = await api<{items: ApiMessage[]}>(`/api/chat/sessions/${id}/messages`);
      clearChatTask();
      setSessionId(id);
      setMessages(data.items.filter((item) => item.role !== "system").map((item) => ({
        role: item.role as "user" | "assistant",
        content: item.content,
        citations: item.citations || []
      })));
      setImage(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return;
      setMessages((prev) => [...prev, {role: "assistant", content: err instanceof Error ? err.message : "加载历史会话失败"}]);
    } finally {
      setHistoryLoading(false);
    }
  }

  async function deleteConversation(id: string, title: string) {
    if (loading && id === sessionId) return;
    const label = title || "新的诊断会话";
    if (!window.confirm(`确定删除「${label}」吗？该历史对话和引用记录会一起删除。`)) return;

    setDeletingSessionId(id);
    try {
      await api(`/api/chat/sessions/${id}`, {method: "DELETE"});
      setConversations((prev) => prev.filter((conversation) => conversation.id !== id));
      if (id === sessionId) {
        clearChatTask();
        setSessionId("");
        setMessages([]);
        setImage(null);
        setQuestion("");
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return;
      setMessages((prev) => [...prev, {role: "assistant", content: err instanceof Error ? err.message : "删除历史会话失败"}]);
    } finally {
      setDeletingSessionId("");
    }
  }

  function startNewConversation() {
    if (loading) return;
    clearChatTask();
    setSessionId("");
    setMessages([]);
    setImage(null);
    setQuestion("");
  }

  const latestAssistantMessage = [...messages].reverse().find((message) => (
    message.role === "assistant" && Boolean(message.citations?.length)
  ));

  return (
    <AppShell>
      <div className="flex h-full min-h-0">
        <aside className="hidden w-80 shrink-0 border-r border-line bg-white md:flex md:min-h-0 md:flex-col">
          <div className="flex h-16 items-center justify-between border-b border-line px-4">
            <div className="flex items-center gap-2">
              <History className="h-4 w-4 text-accent" />
              <h2 className="text-sm font-semibold">历史对话</h2>
            </div>
            <button
              type="button"
              onClick={startNewConversation}
              disabled={loading}
              className="flex h-9 w-9 items-center justify-center rounded-md border border-line text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              title="新建对话"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>
          <div className="border-b border-line p-3">
            <button
              type="button"
              onClick={startNewConversation}
              disabled={loading}
              className={`flex h-10 w-full items-center justify-center gap-2 rounded-md border text-sm font-medium disabled:opacity-50 ${sessionId ? "border-line bg-white text-slate-700 hover:bg-slate-50" : "border-teal-200 bg-teal-50 text-accent"}`}
            >
              <MessageSquarePlus className="h-4 w-4" />
              新建对话
            </button>
          </div>
          <div className="flex-1 overflow-auto p-3">
            {conversations.length === 0 ? (
              <div className="rounded-md border border-dashed border-line p-4 text-sm leading-6 text-slate-500">
                暂无历史对话
              </div>
            ) : (
              <div className="space-y-2">
                {conversations.map((conversation) => (
                  <div
                    key={conversation.id}
                    className={`group flex items-stretch gap-2 rounded-md border p-2 transition ${conversation.id === sessionId ? "border-teal-200 bg-teal-50" : "border-line bg-white hover:bg-slate-50"}`}
                  >
                    <button
                      type="button"
                      disabled={loading || historyLoading || deletingSessionId === conversation.id}
                      onClick={() => loadConversation(conversation.id)}
                      className="min-w-0 flex-1 rounded px-1 py-1 text-left disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <div className="line-clamp-1 text-sm font-semibold text-slate-800">{conversation.title || "新的诊断会话"}</div>
                      <div className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{conversation.last_message || "空会话"}</div>
                      <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
                        <span>{conversation.message_count} 条</span>
                        <span>{formatConversationTime(conversation.updated_at)}</span>
                      </div>
                    </button>
                    <button
                      type="button"
                      disabled={(loading && conversation.id === sessionId) || deletingSessionId === conversation.id}
                      onClick={() => deleteConversation(conversation.id, conversation.title)}
                      className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-slate-400 opacity-100 hover:bg-rose-50 hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-40 md:opacity-0 md:group-hover:opacity-100"
                      title="删除对话"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>
        <section className="flex min-h-0 min-w-0 flex-1 flex-col">
          <header className="flex h-16 shrink-0 items-center justify-between border-b border-line bg-white px-6">
            <div>
              <h1 className="text-lg font-semibold">诊断工作台</h1>
              <p className="text-xs text-slate-500">{sessionId ? "当前对话会记住上下文，并持续追加历史消息" : "新对话将在第一次发送后自动保存"}</p>
            </div>
            <select className="h-10 rounded-md border border-line bg-white px-3 text-sm" value={knowledgeBaseId} onChange={(e) => setKnowledgeBaseId(e.target.value)}>
              {kbs.map((kb) => <option key={kb.id} value={kb.id}>{kb.name}</option>)}
            </select>
          </header>
          <div className="min-h-0 flex-1 overflow-auto px-6 py-5 pb-6">
            <div className="mx-auto max-w-4xl space-y-4">
              {messages.length === 0 && (
                <div className="rounded-md border border-line bg-white p-6">
                  <h2 className="text-base font-semibold">开始一次维修诊断</h2>
                  <p className="mt-2 text-sm leading-6 text-slate-600">描述故障现象、故障码、车辆状态或上传仪表/零部件图片。系统会检索知识库并返回可追溯诊断建议。</p>
                </div>
              )}
              {messages.map((message, index) => (
                <article key={index} className={`rounded-md border p-4 ${message.role === "user" ? "border-teal-200 bg-teal-50" : "border-line bg-white"}`}>
                  <div className="mb-2 text-xs font-semibold text-slate-500">{message.role === "user" ? "技师" : "诊断助手"}</div>
                  {message.role === "assistant" && message.imageDescription && (
                    <div className="mb-3 rounded-md border border-sky-100 bg-sky-50 p-3 text-xs leading-5 text-sky-800">
                      <div className="mb-1 font-semibold">图片理解结果</div>
                      {message.imageDescription}
                    </div>
                  )}
                  {message.role === "assistant" ? <DiagnosticCards content={message.content} /> : <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-6">{message.content}</pre>}
                  {message.role === "assistant" && message.citations?.length ? (
                    <div className="mt-3 xl:hidden">
                      <EvidenceTracePanel message={message} compact />
                    </div>
                  ) : null}
                </article>
              ))}
              {loading && <PendingAssistantMessage elapsedSeconds={elapsedSeconds} hasImage={pendingHasImage} />}
              <div ref={messagesEndRef} />
            </div>
          </div>
          <form onSubmit={submit} className="shrink-0 border-t border-line bg-white px-6 pb-6 pt-4">
            <div className="mx-auto flex max-w-4xl items-end gap-3">
              <label className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-md border border-line hover:bg-slate-50" title="上传故障图片">
                <ImagePlus className="h-5 w-5 text-slate-600" />
                <input type="file" accept="image/*" className="hidden" onChange={(e) => setImage(e.target.files?.[0] || null)} />
              </label>
              <textarea className="focus-ring min-h-11 flex-1 resize-none rounded-md border border-line px-3 py-3 text-sm" value={question} onChange={(e) => setQuestion(e.target.value)} />
              <button disabled={loading} className="flex h-11 items-center gap-2 rounded-md bg-accent px-4 text-sm font-semibold text-white disabled:opacity-60">
                <Send className="h-4 w-4" />
                发送
              </button>
            </div>
            {image && <div className="mx-auto mt-2 max-w-4xl text-xs text-slate-500">已选择图片：{image.name}</div>}
          </form>
        </section>
        <aside className="hidden h-full min-h-0 w-96 flex-col overflow-hidden border-l border-line bg-white p-5 xl:flex">
          <div className="shrink-0">
            <EvidenceTracePanel message={latestAssistantMessage} />
          </div>
          <div className="mt-5 flex min-h-0 flex-1 flex-col">
            <div className="flex shrink-0 items-center justify-between">
              <h2 className="text-sm font-semibold">最近引用</h2>
              <span className="text-xs text-slate-400">{messages.flatMap((m) => m.citations || []).length} 条</span>
            </div>
            <div className="mt-4 min-h-0 flex-1 overflow-y-auto pr-1">
              <div className="space-y-3 pb-1">
                {messages.flatMap((m) => m.citations || []).slice(-6).map((citation) => (
                  <CitationEvidenceCard key={citation.id} citation={citation} />
                ))}
              </div>
            </div>
          </div>
        </aside>
      </div>
    </AppShell>
  );
}

function DiagnosticCards({content}: {content: string}) {
  const sections = splitDiagnosticSections(content);
  if (sections.length < 2) {
    return <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-6">{content}</pre>;
  }
  return (
    <div className="space-y-3">
      {sections.map((section) => (
        <section key={section.title} className={`rounded-md border p-3 ${section.title.includes("安全") ? "border-amber-200 bg-amber-50" : "border-line bg-white"}`}>
          <div className={`mb-2 text-sm font-semibold ${section.title.includes("安全") ? "text-amber-800" : "text-slate-800"}`}>{section.title}</div>
          <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-6 text-slate-700">{section.body}</pre>
        </section>
      ))}
    </div>
  );
}

function EvidenceTracePanel({message, compact = false}: {message?: Message; compact?: boolean}) {
  const citations = message?.citations || [];
  const topCitation = citations[0];
  const terms = evidenceTerms(citations);
  const sourceLabel = topCitation ? (topCitation.sources || []).join(" + ") || "vector" : "-";
  const metadataLabel = topCitation ? formatMetadataLabel(topCitation) : "-";
  const topScore = topCitation ? formatScore(topCitation.rerank_score ?? topCitation.score) : "-";

  if (!message && compact) return null;

  return (
    <section className={`rounded-md border border-line bg-white ${compact ? "p-3" : "p-4"}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <FileSearch className="h-4 w-4 text-accent" />
          <h2 className="text-sm font-semibold">证据链</h2>
        </div>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500">
          {citations.length || 0} 条引用
        </span>
      </div>
      {citations.length === 0 ? (
        <div className="mt-3 rounded-md border border-dashed border-line p-3 text-xs leading-5 text-slate-500">
          暂无可展示证据
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          <TraceRow icon={Search} label="检索关键词" value={terms.join(" / ") || "-"} />
          <TraceRow icon={BrainCircuit} label="召回方式" value={sourceLabel} />
          <TraceRow icon={ListChecks} label="精排 Top1" value={topScore} />
          <TraceRow icon={ShieldCheck} label="引用定位" value={metadataLabel} />
          {terms.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-1">
              {terms.slice(0, 10).map((term) => (
                <span key={term} className="rounded-full bg-teal-50 px-2 py-0.5 text-[11px] font-medium text-teal-700">
                  {term}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function TraceRow({icon: Icon, label, value}: {icon: LucideIcon; label: string; value: string}) {
  return (
    <div className="grid grid-cols-[18px_76px_1fr] items-start gap-2 text-xs leading-5">
      <Icon className="mt-0.5 h-4 w-4 text-slate-400" />
      <span className="font-medium text-slate-500">{label}</span>
      <span className="break-words text-slate-700">{value}</span>
    </div>
  );
}

function CitationEvidenceCard({citation}: {citation: Citation}) {
  const metadata = citation.metadata || {};
  const chips = [
    metadata.page ? `第 ${metadata.page} 页` : "",
    metadata.heading || "",
    ...(metadata.system || []),
    ...(metadata.dtc || []),
    ...(citation.retrieval_terms || []),
    ...(citation.keyword_matches || []),
  ].filter(Boolean).slice(0, 6);

  return (
    <div className="rounded-md border border-line p-3">
      <div className="text-xs font-semibold">{citation.title}</div>
      <div className="mt-1 text-xs text-slate-500">{citation.filename}</div>
      {chips.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {chips.map((chip) => (
            <span key={chip} className="rounded-full bg-teal-50 px-2 py-0.5 text-[11px] font-medium text-teal-700">{chip}</span>
          ))}
        </div>
      )}
      <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-slate-500">
        <span>最终 {formatScore(citation.score)}</span>
        <span>向量 {formatScore(citation.vector_score)}</span>
        <span>重排 {formatScore(citation.rerank_score)}</span>
        <span>{(citation.sources || []).join(" + ") || "vector"}</span>
      </div>
      {citation.retrieval_terms?.length ? (
        <div className="mt-2 text-[11px] leading-5 text-slate-500">
          检索词：{citation.retrieval_terms.slice(0, 6).join(" / ")}
        </div>
      ) : null}
      <p className="mt-2 line-clamp-5 text-xs leading-5 text-slate-600">{citation.content}</p>
    </div>
  );
}

function evidenceTerms(citations: Citation[]) {
  const values = citations.flatMap((citation) => [
    ...(citation.retrieval_terms || []),
    ...(citation.keyword_matches || []),
    ...(citation.metadata?.dtc || []),
    ...(citation.metadata?.system || []),
  ]);
  return Array.from(new Set(values.filter(Boolean))).slice(0, 12);
}

function formatMetadataLabel(citation: Citation) {
  const metadata = citation.metadata || {};
  const parts = [
    metadata.page ? `第 ${metadata.page} 页` : "",
    metadata.heading || "",
    ...(metadata.system || []),
    ...(metadata.dtc || []),
    metadata.vehicle_model ? `车型 ${metadata.vehicle_model}` : "",
  ].filter(Boolean);
  return parts.slice(0, 5).join(" / ") || citation.title;
}

function splitDiagnosticSections(content: string) {
  const matches = Array.from(content.matchAll(/(?:^|\n)(\d+\.\s*[^\n]+)\n/g));
  if (!matches.length) return [];
  return matches.map((match, index) => {
    const start = (match.index || 0) + (match[0].startsWith("\n") ? 1 : 0);
    const bodyStart = start + match[1].length;
    const end = index + 1 < matches.length ? matches[index + 1].index || content.length : content.length;
    return {
      title: match[1].trim(),
      body: content.slice(bodyStart, end).trim(),
    };
  }).filter((section) => section.body);
}

function formatScore(value?: number) {
  return typeof value === "number" ? value.toFixed(3) : "-";
}

function formatConversationTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function PendingAssistantMessage({elapsedSeconds, hasImage}: {elapsedSeconds: number; hasImage: boolean}) {
  const steps = hasImage ? imagePendingSteps : textPendingSteps;
  const currentStep = steps[Math.floor(elapsedSeconds / 3) % steps.length];
  const Icon = currentStep.icon;

  return (
    <article className="rounded-md border border-line bg-white p-4" aria-live="polite">
      <div className="mb-3 text-xs font-semibold text-slate-500">诊断助手</div>
      <div className="flex items-center gap-3 text-sm text-slate-700">
        <div className="thinking-icon" aria-hidden="true">
          <Icon className="h-4 w-4" />
        </div>
        <div className="flex min-w-0 items-center gap-2">
          <span className="font-medium">{currentStep.label}</span>
          <span className="thinking-dots" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          {elapsedSeconds > 10 && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
              {elapsedSeconds}s
            </span>
          )}
        </div>
      </div>
    </article>
  );
}
