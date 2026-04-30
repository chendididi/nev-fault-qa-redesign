export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export type User = {
  id: string;
  email: string;
  name: string;
  role: "admin" | "technician";
  is_active?: boolean;
};

export function getToken() {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("token");
}

export function setToken(token: string) {
  window.localStorage.setItem("token", token);
}

export function clearToken() {
  window.localStorage.removeItem("token");
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_BASE}${path}`, {...options, headers});
  if (!response.ok) {
    const message = await responseMessage(response);
    if (response.status === 401 && typeof window !== "undefined") {
      clearToken();
      window.location.href = "/login";
    }
    throw new ApiError(response.status, message);
  }
  return response.json();
}

async function responseMessage(response: Response) {
  const text = await response.text();
  if (!text) return `HTTP ${response.status}`;
  try {
    const data = JSON.parse(text);
    if (typeof data.detail === "string") {
      if (response.status === 401) return "登录已过期，请重新登录。";
      return data.detail;
    }
  } catch {
    return text;
  }
  return text;
}
