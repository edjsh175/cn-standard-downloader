import type { TaskCreatePayload, TaskDetail, TaskResultResponse } from "./types";

const JSON_HEADERS = {
  "Content-Type": "application/json",
};

async function request<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
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

export async function fetchTables(): Promise<string[]> {
  const payload = await request<{ tables: string[] }>("/api/tables");
  return payload.tables ?? [];
}

export async function createTask(payload: TaskCreatePayload): Promise<TaskDetail> {
  return request<TaskDetail>("/api/tasks", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export async function fetchTask(taskId: string): Promise<TaskDetail> {
  return request<TaskDetail>(`/api/tasks/${taskId}`);
}

export async function fetchTaskResult(taskId: string): Promise<TaskResultResponse> {
  return request<TaskResultResponse>(`/api/tasks/${taskId}/result`);
}

export async function cancelTask(taskId: string): Promise<TaskDetail> {
  return request<TaskDetail>(`/api/tasks/${taskId}/cancel`, {
    method: "POST",
    headers: JSON_HEADERS,
  });
}
