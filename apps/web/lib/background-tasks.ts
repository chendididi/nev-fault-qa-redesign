"use client";

import { API_BASE, api, getToken } from "@/lib/api";

export type TaskStatus = "idle" | "running" | "success" | "error";

export type CitationMetadata = {
  page?: number;
  heading?: string;
  system?: string[];
  dtc?: string[];
  vehicle_model?: string;
  keywords?: string[];
};

export type Citation = {
  id: string;
  score: number;
  vector_score?: number;
  rerank_score?: number;
  keyword_matches?: string[];
  retrieval_terms?: string[];
  sources?: string[];
  metadata?: CitationMetadata;
  content: string;
  title: string;
  filename: string;
};

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  imageDescription?: string | null;
};

export type ChatTaskSnapshot = {
  status: TaskStatus;
  sessionId: string;
  messages: ChatMessage[];
  pendingHasImage: boolean;
  startedAt: number | null;
  completedAt: number | null;
  error: string;
};

export type ModelCheck = {
  name: "models" | "chat" | "vision_ocr" | "embedding" | "rerank" | string;
  ok: boolean;
  message: string;
  duration_ms?: number;
};

export type ModelTestTaskSnapshot = {
  status: TaskStatus;
  message: string;
  checks: ModelCheck[];
  startedAt: number | null;
  completedAt: number | null;
  error: string;
};

type ChatTaskInput = {
  question: string;
  knowledgeBaseId: string;
  sessionId: string;
  image: File | null;
  messages: ChatMessage[];
};

export type ModelEndpoint = {
  id?: string;
  client_id?: string;
  name: string;
  provider_type: "remote_api" | "vllm" | "ollama" | "llama_cpp" | "lm_studio" | "demo_cache" | "local";
  base_url: string;
  api_key: string;
  capabilities: string[];
  timeout_seconds: number;
  is_active: boolean;
};

export type ModelRoute = {
  task: "chat" | "vision_ocr" | "embedding" | "rerank" | "fallback_chat";
  endpoint_id: string | null;
  model_name: string;
  temperature: number;
  max_tokens?: number | null;
  enabled: boolean;
};

export type ModelTopology = {
  demo_mode: "real" | "fallback" | "always";
  endpoints: ModelEndpoint[];
  routes: Record<string, ModelRoute>;
};

type ModelConfigPayload = ModelTopology | Record<string, unknown>;

type ModelTestResponse = {
  ok: boolean;
  checks: ModelCheck[];
};

const chatListeners = new Set<() => void>();
const modelTestListeners = new Set<() => void>();

let chatTask: ChatTaskSnapshot = {
  status: "idle",
  sessionId: "",
  messages: [],
  pendingHasImage: false,
  startedAt: null,
  completedAt: null,
  error: "",
};

let modelTestTask: ModelTestTaskSnapshot = {
  status: "idle",
  message: "",
  checks: [],
  startedAt: null,
  completedAt: null,
  error: "",
};

export function subscribeChatTask(listener: () => void) {
  chatListeners.add(listener);
  return () => chatListeners.delete(listener);
}

export function subscribeModelTestTask(listener: () => void) {
  modelTestListeners.add(listener);
  return () => modelTestListeners.delete(listener);
}

export function getChatTaskSnapshot() {
  return chatTask;
}

export function getModelTestTaskSnapshot() {
  return modelTestTask;
}

export function clearChatTask() {
  if (chatTask.status === "running") return false;
  setChatTask({
    status: "idle",
    sessionId: "",
    messages: [],
    pendingHasImage: false,
    startedAt: null,
    completedAt: null,
    error: "",
  });
  return true;
}

export function startChatTask(input: ChatTaskInput) {
  if (chatTask.status === "running") return false;

  const text = input.question.trim();
  if (!text) return false;

  const form = new FormData();
  form.set("question", text);
  if (input.knowledgeBaseId) form.set("knowledge_base_id", input.knowledgeBaseId);
  if (input.sessionId) form.set("session_id", input.sessionId);
  if (input.image) form.set("image", input.image);

  const userMessage: ChatMessage = {role: "user", content: text};
  setChatTask({
    status: "running",
    sessionId: input.sessionId,
    messages: [...input.messages, userMessage],
    pendingHasImage: Boolean(input.image),
    startedAt: Date.now(),
    completedAt: null,
    error: "",
  });

  void streamChat(form)
    .catch((err) => {
      const message = err instanceof Error ? err.message : "请求失败";
      setChatTask({
        ...chatTask,
        status: "error",
        messages: [...chatTask.messages, {role: "assistant", content: message}],
        pendingHasImage: false,
        completedAt: Date.now(),
        error: message,
      });
    });

  return true;
}

async function streamChat(form: FormData) {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE}/api/chat/stream`, {method: "POST", body: form, headers});
  if (!response.ok || !response.body) {
    throw new Error(await streamErrorMessage(response));
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {stream: true});
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";
    for (const event of events) {
      const line = event.split("\n").find((item) => item.startsWith("data: "));
      if (!line) continue;
      const data = JSON.parse(line.slice(6));
      handleChatStreamEvent(data);
    }
  }
}

function handleChatStreamEvent(data: Record<string, unknown>) {
  if (data.type === "start") {
    setChatTask({
      ...chatTask,
      sessionId: String(data.session_id || chatTask.sessionId),
      pendingHasImage: false,
    });
    return;
  }
  if (data.type === "delta") {
    const content = String(data.content || "");
    const messages = [...chatTask.messages];
    const last = messages[messages.length - 1];
    if (last?.role === "assistant") {
      messages[messages.length - 1] = {...last, content: last.content + content};
    } else {
      messages.push({role: "assistant", content});
    }
    setChatTask({...chatTask, messages});
    return;
  }
  if (data.type === "done") {
    const messages = [...chatTask.messages];
    const last = messages[messages.length - 1];
    const citations = (data.citations || []) as Citation[];
    const answer = String(data.answer || "");
    if (last?.role === "assistant") {
      messages[messages.length - 1] = {...last, content: answer || last.content, citations};
    } else {
      messages.push({role: "assistant", content: answer, citations});
    }
    setChatTask({
      ...chatTask,
      status: "success",
      sessionId: String(data.session_id || chatTask.sessionId),
      messages,
      pendingHasImage: false,
      completedAt: Date.now(),
      error: "",
    });
  }
}

async function streamErrorMessage(response: Response) {
  const text = await response.text();
  if (!text) return `HTTP ${response.status}`;
  try {
    const data = JSON.parse(text);
    return typeof data.detail === "string" ? data.detail : text;
  } catch {
    return text;
  }
}

export function startModelTestTask(payload: ModelConfigPayload) {
  if (modelTestTask.status === "running") return false;

  setModelTestTask({
    status: "running",
    message: "测试中...",
    checks: [],
    startedAt: Date.now(),
    completedAt: null,
    error: "",
  });

  void api<ModelTestResponse>("/api/admin/model-config/test", {method: "POST", body: JSON.stringify(payload)})
    .then((data) => {
      setModelTestTask({
        status: data.ok ? "success" : "error",
        message: data.ok ? "所有模型检查通过" : "部分模型检查失败",
        checks: data.checks,
        startedAt: modelTestTask.startedAt,
        completedAt: Date.now(),
        error: data.ok ? "" : "部分模型检查失败",
      });
    })
    .catch((err) => {
      const message = err instanceof Error ? err.message : "测试失败";
      setModelTestTask({
        status: "error",
        message,
        checks: [],
        startedAt: modelTestTask.startedAt,
        completedAt: Date.now(),
        error: message,
      });
    });

  return true;
}

function setChatTask(next: ChatTaskSnapshot) {
  chatTask = next;
  chatListeners.forEach((listener) => listener());
}

function setModelTestTask(next: ModelTestTaskSnapshot) {
  modelTestTask = next;
  modelTestListeners.forEach((listener) => listener());
}
