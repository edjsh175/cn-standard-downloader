// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { downloadApiFile, fetchTables, setApiToken } from "./api";

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function fileResponse(): Response {
  return new Response("file", {
    status: 200,
    headers: { "Content-Disposition": "attachment; filename=\"task.log\"" },
  });
}

function lastRequestHeaders(): Headers {
  const fetchMock = vi.mocked(fetch);
  const [, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1] ?? [];
  return new Headers(init?.headers);
}

describe("api authorization", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    setApiToken("");
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ tables: [] })));
    vi.spyOn(window.URL, "createObjectURL").mockReturnValue("blob:test");
    vi.spyOn(window.URL, "revokeObjectURL").mockImplementation(() => undefined);
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  test("does not attach authorization without a runtime token", async () => {
    await fetchTables();

    expect(lastRequestHeaders().has("Authorization")).toBe(false);
  });

  test("attaches the runtime token to API requests", async () => {
    setApiToken("runtime-token");

    await fetchTables();

    expect(lastRequestHeaders().get("Authorization")).toBe("Bearer runtime-token");
  });

  test("does not send the runtime token to external absolute download URLs", async () => {
    setApiToken("runtime-token");
    vi.mocked(fetch).mockResolvedValueOnce(fileResponse());

    await downloadApiFile("https://example.com/export.xlsx", "export.xlsx");

    expect(lastRequestHeaders().has("Authorization")).toBe(false);
  });

  test("attaches the runtime token to API download URLs", async () => {
    setApiToken("runtime-token");
    vi.mocked(fetch).mockResolvedValueOnce(fileResponse());

    await downloadApiFile("api/tasks/task-1/artifacts/log_file", "task.log");

    expect(lastRequestHeaders().get("Authorization")).toBe("Bearer runtime-token");
  });
});
