"use client";

import { FormEvent, useEffect, useState, useSyncExternalStore } from "react";
import { Activity, Plus, PlugZap, Save, Server, ShieldCheck } from "lucide-react";
import { AppShell } from "@/components/shell";
import { api } from "@/lib/api";
import {
  getModelTestTaskSnapshot,
  startModelTestTask,
  subscribeModelTestTask,
  type ModelEndpoint,
  type ModelRoute,
  type ModelTopology,
} from "@/lib/background-tasks";

const providerOptions = [
  ["remote_api", "远端 API"],
  ["vllm", "vLLM"],
  ["ollama", "Ollama"],
  ["llama_cpp", "llama.cpp"],
  ["lm_studio", "LM Studio"],
  ["demo_cache", "Demo Cache"],
  ["local", "本地检索"],
] as const;

const capabilityOptions = ["chat", "vision", "embedding", "rerank"] as const;

const routeTasks: Array<{task: ModelRoute["task"]; label: string; hint: string}> = [
  {task: "chat", label: "主聊天", hint: "维修问答生成"},
  {task: "vision_ocr", label: "图片理解/OCR", hint: "仪表、故障码、维修资料图片"},
  {task: "embedding", label: "Embedding", hint: "知识库向量化与检索"},
  {task: "rerank", label: "Rerank", hint: "检索结果重排"},
  {task: "fallback_chat", label: "Fallback", hint: "主模型失败时兜底"},
];

const defaultRoutes: Record<string, ModelRoute> = {
  chat: {task: "chat", endpoint_id: null, model_name: "qwen-vl-demo", temperature: 0.2, max_tokens: null, enabled: true},
  vision_ocr: {task: "vision_ocr", endpoint_id: null, model_name: "qwen-vl-demo", temperature: 0.1, max_tokens: null, enabled: true},
  embedding: {task: "embedding", endpoint_id: null, model_name: "BAAI/bge-m3", temperature: 0.2, max_tokens: null, enabled: true},
  rerank: {task: "rerank", endpoint_id: null, model_name: "BAAI/bge-reranker-v2-m3", temperature: 0.2, max_tokens: null, enabled: true},
  fallback_chat: {task: "fallback_chat", endpoint_id: null, model_name: "demo-cache", temperature: 0.2, max_tokens: null, enabled: true},
};

export default function ModelPage() {
  const [topology, setTopology] = useState<ModelTopology>(() => normalizeTopology({}));
  const [message, setMessage] = useState("");
  const [saveLoading, setSaveLoading] = useState(false);
  const modelTestTask = useSyncExternalStore(subscribeModelTestTask, getModelTestTaskSnapshot, getModelTestTaskSnapshot);
  const testLoading = modelTestTask.status === "running";
  const loading = saveLoading || testLoading;
  const displayMessage = modelTestTask.status === "idle" ? message : modelTestTask.message;
  const displayChecks = modelTestTask.status === "idle" ? [] : modelTestTask.checks;

  useEffect(() => {
    api<Partial<ModelTopology>>("/api/admin/model-config")
      .then((data) => setTopology(normalizeTopology(data)))
      .catch((err) => setMessage(err instanceof Error ? err.message : "加载失败"));
  }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaveLoading(true);
    setMessage("");
    try {
      const data = await api<ModelTopology>("/api/admin/model-config", {method: "PUT", body: JSON.stringify(topology)});
      setTopology(normalizeTopology(data));
      setMessage("配置已保存");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaveLoading(false);
    }
  }

  function test() {
    startModelTestTask(topology);
  }

  function addEndpoint(providerType: ModelEndpoint["provider_type"] = "vllm") {
    const endpoint = createEndpoint(providerType);
    setTopology((prev) => ({...prev, endpoints: [...prev.endpoints, endpoint]}));
  }

  function updateEndpoint(index: number, patch: Partial<ModelEndpoint>) {
    setTopology((prev) => ({
      ...prev,
      endpoints: prev.endpoints.map((endpoint, itemIndex) => itemIndex === index ? {...endpoint, ...patch} : endpoint),
    }));
  }

  function updateRoute(task: ModelRoute["task"], patch: Partial<ModelRoute>) {
    setTopology((prev) => ({
      ...prev,
      routes: {
        ...prev.routes,
        [task]: {...defaultRoutes[task], ...prev.routes[task], ...patch, task},
      },
    }));
  }

  function toggleCapability(index: number, capability: string) {
    const endpoint = topology.endpoints[index];
    const next = endpoint.capabilities.includes(capability)
      ? endpoint.capabilities.filter((item) => item !== capability)
      : [...endpoint.capabilities, capability];
    updateEndpoint(index, {capabilities: next});
  }

  return (
    <AppShell pageScrollable>
      <div className="min-h-full px-4 py-5 md:px-6">
      <div className="mx-auto max-w-6xl pb-10">
        <header className="mb-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-xl font-semibold">模型配置</h1>
            <p className="mt-1 text-sm text-slate-500">统一接入 vLLM、Ollama、llama.cpp、LM Studio 和第三方 OpenAI-compatible API。</p>
          </div>
          <div className="flex gap-2">
            <button type="button" onClick={() => addEndpoint("vllm")} className="flex h-10 items-center gap-2 rounded-md border border-line bg-white px-4 text-sm">
              <Plus className="h-4 w-4" />
              新增端点
            </button>
          </div>
        </header>

        <form onSubmit={save} className="space-y-5">
          <section className="rounded-md border border-line bg-white p-5">
            <div className="mb-4 flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-accent" />
              <h2 className="text-sm font-semibold">演示策略</h2>
            </div>
            <select
              className="h-10 rounded-md border border-line px-3 text-sm"
              value={topology.demo_mode}
              onChange={(event) => setTopology((prev) => ({...prev, demo_mode: event.target.value as ModelTopology["demo_mode"]}))}
            >
              <option value="fallback">真实模型优先，失败后 Demo Cache</option>
              <option value="real">只使用真实模型</option>
              <option value="always">始终使用 Demo Cache</option>
            </select>
          </section>

          <section className="rounded-md border border-line bg-white p-5">
            <div className="mb-4 flex items-center gap-2">
              <Server className="h-4 w-4 text-accent" />
              <h2 className="text-sm font-semibold">端点管理</h2>
            </div>
            <div className="space-y-4">
              {topology.endpoints.map((endpoint, index) => (
                <div key={endpointKey(endpoint)} className="grid gap-3 rounded-md border border-line p-4 lg:grid-cols-[1.1fr_150px_1.5fr_1fr_110px]">
                  <input className="h-10 rounded-md border border-line px-3 text-sm" value={endpoint.name} onChange={(event) => updateEndpoint(index, {name: event.target.value})} />
                  <select className="h-10 rounded-md border border-line px-3 text-sm" value={endpoint.provider_type} onChange={(event) => updateEndpoint(index, {provider_type: event.target.value as ModelEndpoint["provider_type"]})}>
                    {providerOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                  <input className="h-10 rounded-md border border-line px-3 text-sm" placeholder="Base URL，例如 http://server:8008/v1" value={endpoint.base_url} onChange={(event) => updateEndpoint(index, {base_url: event.target.value})} />
                  <input className="h-10 rounded-md border border-line px-3 text-sm" placeholder="API Key，可留空" value={endpoint.api_key} onChange={(event) => updateEndpoint(index, {api_key: event.target.value})} />
                  <input className="h-10 rounded-md border border-line px-3 text-sm" type="number" value={endpoint.timeout_seconds} onChange={(event) => updateEndpoint(index, {timeout_seconds: Number(event.target.value)})} />
                  <div className="flex flex-wrap gap-2 lg:col-span-4">
                    {capabilityOptions.map((capability) => (
                      <button
                        key={capability}
                        type="button"
                        onClick={() => toggleCapability(index, capability)}
                        className={`rounded-md border px-3 py-1 text-xs ${endpoint.capabilities.includes(capability) ? "border-teal-200 bg-teal-50 text-accent" : "border-line bg-white text-slate-600"}`}
                      >
                        {capability}
                      </button>
                    ))}
                  </div>
                  <label className="flex items-center gap-2 text-sm text-slate-600">
                    <input type="checkbox" checked={endpoint.is_active} onChange={(event) => updateEndpoint(index, {is_active: event.target.checked})} />
                    启用
                  </label>
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-md border border-line bg-white p-5">
            <div className="mb-4 flex items-center gap-2">
              <Activity className="h-4 w-4 text-accent" />
              <h2 className="text-sm font-semibold">任务路由</h2>
            </div>
            <div className="overflow-x-auto rounded-md border border-line">
              <table className="min-w-[900px] w-full text-left text-sm">
                <thead className="bg-panel text-xs text-slate-500">
                  <tr>
                    <th className="px-3 py-3">任务</th>
                    <th className="px-3 py-3">端点</th>
                    <th className="px-3 py-3">模型名</th>
                    <th className="px-3 py-3">温度</th>
                    <th className="px-3 py-3">Max Tokens</th>
                    <th className="px-3 py-3">启用</th>
                  </tr>
                </thead>
                <tbody>
                  {routeTasks.map(({task, label, hint}) => {
                    const route = {...defaultRoutes[task], ...topology.routes[task]};
                    return (
                      <tr key={task} className="border-t border-line">
                        <td className="px-3 py-3">
                          <div className="font-medium">{label}</div>
                          <div className="text-xs text-slate-500">{hint}</div>
                        </td>
                        <td className="px-3 py-3">
                          <select className="h-10 w-full rounded-md border border-line px-3" value={route.endpoint_id || ""} onChange={(event) => updateRoute(task, {endpoint_id: event.target.value || null})}>
                            <option value="">未选择</option>
                            {topology.endpoints.map((endpoint) => <option key={endpointKey(endpoint)} value={endpointKey(endpoint)}>{endpoint.name}</option>)}
                          </select>
                        </td>
                        <td className="px-3 py-3">
                          <input className="h-10 w-full rounded-md border border-line px-3" value={route.model_name} onChange={(event) => updateRoute(task, {model_name: event.target.value})} />
                        </td>
                        <td className="px-3 py-3">
                          <input className="h-10 w-24 rounded-md border border-line px-3" type="number" step="0.1" value={route.temperature} onChange={(event) => updateRoute(task, {temperature: Number(event.target.value)})} />
                        </td>
                        <td className="px-3 py-3">
                          <input className="h-10 w-28 rounded-md border border-line px-3" type="number" value={route.max_tokens || ""} onChange={(event) => updateRoute(task, {max_tokens: event.target.value ? Number(event.target.value) : null})} />
                        </td>
                        <td className="px-3 py-3">
                          <input type="checkbox" checked={route.enabled} onChange={(event) => updateRoute(task, {enabled: event.target.checked})} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {displayMessage && <div className="rounded-md border border-line bg-panel p-3 text-sm">{displayMessage}</div>}
          {displayChecks.length > 0 && (
            <div className="space-y-2 rounded-md border border-line bg-white p-4">
              {displayChecks.map((check) => (
                <div key={check.name} className="grid gap-2 text-sm md:grid-cols-[70px_130px_90px_1fr]">
                  <span className={check.ok ? "text-emerald-700" : "text-red-700"}>{check.ok ? "通过" : "失败"}</span>
                  <span className="font-medium">{check.name}</span>
                  <span className="text-slate-500">{typeof check.duration_ms === "number" ? `${check.duration_ms} ms` : ""}</span>
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
              测试当前路由
            </button>
          </div>
        </form>
      </div>
      </div>
    </AppShell>
  );
}

function normalizeTopology(input: Partial<ModelTopology>): ModelTopology {
  const endpoints = input.endpoints?.length ? input.endpoints : [
    createEndpoint("vllm", "学校 4090 vLLM", "http://localhost:8008/v1", ["chat", "vision"]),
    createEndpoint("local", "本地 BGE 检索模型", "", ["embedding", "rerank"]),
    createEndpoint("demo_cache", "Demo Cache 演示兜底", "", ["chat", "vision"]),
  ];
  const routes = {...defaultRoutes, ...(input.routes || {})};
  for (const task of routeTasks) {
    if (!routes[task.task]) routes[task.task] = defaultRoutes[task.task];
  }
  return {
    demo_mode: input.demo_mode || "fallback",
    endpoints,
    routes,
  };
}

function createEndpoint(
  providerType: ModelEndpoint["provider_type"],
  name?: string,
  baseUrl = "",
  capabilities?: string[],
): ModelEndpoint {
  return {
    client_id: `tmp-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    name: name || providerLabel(providerType),
    provider_type: providerType,
    base_url: baseUrl,
    api_key: "",
    capabilities: capabilities || defaultCapabilities(providerType),
    timeout_seconds: providerType === "demo_cache" ? 5 : 120,
    is_active: true,
  };
}

function endpointKey(endpoint: ModelEndpoint) {
  return endpoint.id || endpoint.client_id || endpoint.name;
}

function providerLabel(providerType: ModelEndpoint["provider_type"]) {
  return providerOptions.find(([value]) => value === providerType)?.[1] || providerType;
}

function defaultCapabilities(providerType: ModelEndpoint["provider_type"]) {
  if (providerType === "local") return ["embedding", "rerank"];
  if (providerType === "demo_cache") return ["chat", "vision"];
  return ["chat", "vision"];
}
