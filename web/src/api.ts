import type { TaskCreatePayload, TaskDetail, TaskResultResponse } from "./types";

const JSON_HEADERS = {
  "Content-Type": "application/json",
};

const API_BASE = (() => {
  const raw = (import.meta.env.VITE_API_BASE_PATH as string | undefined)?.trim();
  if (!raw) {
    return "/api";
  }
  return raw.endsWith("/") ? raw.slice(0, -1) : raw;
})();

const API_TOKEN_SESSION_KEY = "gb-crawler-api-token";
let runtimeApiToken = readStoredApiToken();

function readStoredApiToken(): string {
  try {
    return window.sessionStorage.getItem(API_TOKEN_SESSION_KEY)?.trim() ?? "";
  } catch {
    return "";
  }
}

export function getApiToken(): string {
  return runtimeApiToken;
}

export function setApiToken(token: string): void {
  runtimeApiToken = token.trim();
  try {
    if (runtimeApiToken) {
      window.sessionStorage.setItem(API_TOKEN_SESSION_KEY, runtimeApiToken);
    } else {
      window.sessionStorage.removeItem(API_TOKEN_SESSION_KEY);
    }
  } catch {
    // Keep the in-memory token even when sessionStorage is unavailable.
  }
}

function apiPath(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${normalized}`;
}

function resolveApiUrl(input: string): string {
  const raw = input.trim();
  if (/^https?:\/\//i.test(raw)) {
    return raw;
  }
  if (raw.startsWith("api/")) {
    return apiPath(raw.slice("api".length));
  }
  if (raw.startsWith("/api/")) {
    return apiPath(raw.slice("/api".length));
  }
  if (raw.startsWith("/")) {
    return raw;
  }
  return apiPath(raw);
}

function isApiBaseUrl(input: string): boolean {
  try {
    const target = new URL(input, window.location.origin);
    const apiBase = new URL(API_BASE || "/", window.location.origin);
    const basePath = apiBase.pathname.endsWith("/") ? apiBase.pathname.slice(0, -1) : apiBase.pathname;
    return (
      target.origin === apiBase.origin &&
      (basePath === "" || basePath === "/" || target.pathname === basePath || target.pathname.startsWith(`${basePath}/`))
    );
  } catch {
    return false;
  }
}

function withAuthHeaders(input: string, headers?: HeadersInit): Headers {
  const nextHeaders = new Headers(headers);
  const token = getApiToken();
  if (token && isApiBaseUrl(input)) {
    nextHeaders.set("Authorization", `Bearer ${token}`);
  }
  return nextHeaders;
}

async function request<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    ...init,
    headers: withAuthHeaders(input, init?.headers),
  });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { error?: string };
      if (payload.error) {
        message = payload.error;
      }
    } catch {
      // Ignore JSON parse failures and keep the default message.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

function getDownloadName(contentDisposition: string | null, fallbackName: string): string {
  if (!contentDisposition) {
    return fallbackName;
  }
  const encodedMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (encodedMatch?.[1]) {
    try {
      return decodeURIComponent(encodedMatch[1]);
    } catch {
      return fallbackName;
    }
  }
  const asciiMatch = contentDisposition.match(/filename="([^"]+)"/i);
  return asciiMatch?.[1] || fallbackName;
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { error?: string };
    return payload.error || `HTTP ${response.status}`;
  } catch {
    return `HTTP ${response.status}`;
  }
}

export async function downloadApiFile(url: string, fallbackName: string): Promise<string> {
  const resolvedUrl = resolveApiUrl(url);
  const response = await fetch(resolvedUrl, {
    headers: withAuthHeaders(resolvedUrl),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const blob = await response.blob();
  const downloadName = getDownloadName(response.headers.get("Content-Disposition"), fallbackName);
  const objectUrl = window.URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = downloadName;
    anchor.style.display = "none";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    window.setTimeout(() => window.URL.revokeObjectURL(objectUrl), 1000);
  }
  return downloadName;
}

export async function fetchTables(): Promise<string[]> {
  const payload = await request<{ tables: string[] }>(apiPath("/tables"));
  return payload.tables ?? [];
}

export async function createTask(payload: TaskCreatePayload): Promise<TaskDetail> {
  return request<TaskDetail>(apiPath("/tasks"), {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export async function fetchTask(taskId: string): Promise<TaskDetail> {
  return request<TaskDetail>(apiPath(`/tasks/${taskId}`));
}

export async function fetchTaskResult(taskId: string): Promise<TaskResultResponse> {
  return request<TaskResultResponse>(apiPath(`/tasks/${taskId}/result`));
}

export async function cancelTask(taskId: string): Promise<TaskDetail> {
  return request<TaskDetail>(apiPath(`/tasks/${taskId}/cancel`), {
    method: "POST",
    headers: JSON_HEADERS,
  });
}
