<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import * as XLSX from "xlsx";
import { cancelTask, createTask, downloadApiFile, fetchTaskResult, fetchTables, getApiToken, setApiToken } from "./api";
import type { DirectGrabItem, DuplicatePolicy, TaskCreatePayload, TaskItem, TaskResultResponse } from "./types";

type TabKey = "full" | "search" | "excel" | "url";

const POLL_INTERVAL_MS = 3000;
const LOCAL_STORAGE_KEY = "gb-crawler-recent-task-ids";
const DEFAULT_TABLE_NAME = "gb_standards";
const terminalStates = new Set(["succeeded", "failed", "partial_failed", "cancelled"]);

const tabs: Array<{ key: TabKey; label: string; caption: string }> = [
  { key: "full", label: "完整流程", caption: "搜索、确认、抓取、入库" },
  { key: "search", label: "仅搜索导出", caption: "预览并导出搜索结果" },
  { key: "excel", label: "Excel 抓取", caption: "上传记录后直接入库" },
  { key: "url", label: "URL 批量抓取", caption: "从自由文本提取详情页链接" },
];

const activeTab = ref<TabKey>("full");
const isLoadingTables = ref(false);
const isSubmitting = ref(false);
const isCancelling = ref(false);
const message = ref("");
const messageTone = ref<"info" | "error" | "success">("info");
const tables = ref<string[]>([]);
const recentTaskIds = ref<string[]>([]);
const activeTaskId = ref("");
const activeTaskResult = ref<TaskResultResponse | null>(null);
const activePreviewItems = ref<TaskItem[]>([]);
const activePreviewTaskId = ref("");
const previewSelections = ref<Record<string, boolean>>({});
const isBulkDownloading = ref(false);
const pollingTimer = ref<number | null>(null);
const apiTokenInput = ref(getApiToken());

const form = reactive({
  keywordsText: "",
  perKeywordLimit: "",
  tableName: DEFAULT_TABLE_NAME,
  duplicatePolicy: "overwrite" as DuplicatePolicy,
  urlText: "",
  excelFileName: "",
});

const excelItems = ref<DirectGrabItem[]>([]);

const activeSummary = computed(() => activeTaskResult.value?.result?.summary ?? null);
const activeArtifacts = computed(() => activeTaskResult.value?.result?.artifact_urls ?? {});
const activeErrors = computed(() => activeTaskResult.value?.result?.errors ?? []);
const activeDownloadSummary = computed(() => activeTaskResult.value?.result?.download_summary ?? null);
const activeSearchSummary = computed(() => activeTaskResult.value?.result?.search_summary ?? null);
const downloadablePdfItems = computed(() => activeTaskResult.value?.items.filter((item) => Boolean(item.pdf_download_url)) ?? []);
const previewSelectedCount = computed(
  () => activePreviewItems.value.filter((item) => previewSelections.value[previewItemKey(item)]).length,
);
const previewAllSelected = computed(
  () =>
    activePreviewItems.value.length > 0 &&
    activePreviewItems.value.every((item) => previewSelections.value[previewItemKey(item)]),
);
const previewPartiallySelected = computed(
  () => previewSelectedCount.value > 0 && previewSelectedCount.value < activePreviewItems.value.length,
);
const previewReady = computed(
  () =>
    activeTab.value === "full" &&
    activeTaskResult.value?.status === "succeeded" &&
    activeTaskId.value === activePreviewTaskId.value &&
    activePreviewItems.value.length > 0,
);
const detectedUrlCount = computed(() => extractDetailUrls(form.urlText).length);
const apiTokenButtonLabel = computed(() => (apiTokenInput.value.trim() ? "保存 token" : "清除 token"));

function setBanner(text: string, tone: "info" | "error" | "success" = "info") {
  message.value = text;
  messageTone.value = tone;
}

function parseKeywords(): string[] {
  const tokens = form.keywordsText
    .split(/[,\s;\u3001\uFF0C\uFF1B]+/)
    .map((item) => item.trim())
    .filter(Boolean);
  return [...new Set(tokens)];
}

function normalizedPerKeywordLimit(): number | null {
  const raw = form.perKeywordLimit.trim();
  if (!raw) {
    return null;
  }
  const value = Number.parseInt(raw, 10);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error("每关键词数量限制必须是正整数");
  }
  return value;
}

function extractDetailUrls(text: string): string[] {
  const matches = text.match(/https?:\/\/std\.samr\.gov\.cn\/gb\/search\/gbDetailed\?[^\s"'<>]+/g) ?? [];
  return [...new Set(matches.map((item) => item.trim()))];
}

function isTerminalStatus(status?: string | null): boolean {
  return Boolean(status && terminalStates.has(status));
}

function previewItemKey(item: Pick<TaskItem, "detail_url">): string {
  return item.detail_url;
}

function clearPreviewState() {
  activePreviewTaskId.value = "";
  activePreviewItems.value = [];
  previewSelections.value = {};
}

function syncPreviewState(taskId: string, items: TaskItem[]) {
  const sameTask = activePreviewTaskId.value === taskId;
  const nextSelections: Record<string, boolean> = {};
  for (const item of items) {
    const key = previewItemKey(item);
    nextSelections[key] = sameTask ? previewSelections.value[key] ?? true : true;
  }
  activePreviewTaskId.value = taskId;
  activePreviewItems.value = items;
  previewSelections.value = nextSelections;
}

function setAllPreviewSelections(selected: boolean) {
  const nextSelections: Record<string, boolean> = {};
  for (const item of activePreviewItems.value) {
    nextSelections[previewItemKey(item)] = selected;
  }
  previewSelections.value = nextSelections;
}

function updatePreviewSelection(item: TaskItem, selected: boolean) {
  previewSelections.value = {
    ...previewSelections.value,
    [previewItemKey(item)]: selected,
  };
}

function delay(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function safeFileStem(value: string): string {
  return value.trim().replace(/[\\/:*?"<>|]+/g, "_") || "download";
}

function artifactFallbackName(key: string): string {
  if (key === "log_file") {
    return "task.log";
  }
  return `${safeFileStem(key)}.xlsx`;
}

function pdfFallbackName(item: TaskItem): string {
  return `${safeFileStem(item.code || item.name || `task-item-${item.id}`)}.pdf`;
}

function saveRecentTask(taskId: string) {
  const next = [taskId, ...recentTaskIds.value.filter((item) => item !== taskId)].slice(0, 8);
  recentTaskIds.value = next;
  window.localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(next));
}

function loadRecentTasks() {
  try {
    const raw = window.localStorage.getItem(LOCAL_STORAGE_KEY);
    if (!raw) {
      return;
    }
    const parsed = JSON.parse(raw) as string[];
    recentTaskIds.value = Array.isArray(parsed) ? parsed.filter(Boolean).slice(0, 8) : [];
  } catch {
    recentTaskIds.value = [];
  }
}

function applyApiToken() {
  setApiToken(apiTokenInput.value);
  apiTokenInput.value = getApiToken();
  if (apiTokenInput.value) {
    setBanner("API token 已保存到当前浏览器会话", "success");
    void refreshTables();
  } else {
    tables.value = [];
    setBanner("API token 已清除", "info");
  }
}

async function refreshTables() {
  isLoadingTables.value = true;
  try {
    tables.value = await fetchTables();
    if (!form.tableName.trim()) {
      form.tableName = tables.value[0] ?? DEFAULT_TABLE_NAME;
    }
    setBanner(`已读取 ${tables.value.length} 个数据库表`, "success");
  } catch (error) {
    setBanner((error as Error).message, "error");
  } finally {
    isLoadingTables.value = false;
  }
}

function stopPolling() {
  if (pollingTimer.value !== null) {
    window.clearTimeout(pollingTimer.value);
    pollingTimer.value = null;
  }
}

async function loadTask(taskId: string, keepPolling = true) {
  const result = await fetchTaskResult(taskId);
  activeTaskId.value = taskId;
  activeTaskResult.value = result;
  const isPreviewTask =
    result.status === "succeeded" &&
    result.items.length > 0 &&
    result.items.every((item) => item.item_status === "preview");
  if (isPreviewTask) {
    syncPreviewState(taskId, result.items);
  } else {
    clearPreviewState();
  }

  if (keepPolling && !isTerminalStatus(result.status)) {
    stopPolling();
    pollingTimer.value = window.setTimeout(() => {
      void loadTask(taskId, true);
    }, POLL_INTERVAL_MS);
  } else {
    stopPolling();
  }
  return result;
}

async function submitTask(payload: TaskCreatePayload, successMessage: string) {
  isSubmitting.value = true;
  stopPolling();
  try {
    const task = await createTask(payload);
    saveRecentTask(task.id);
    await loadTask(task.id, true);
    setBanner(successMessage, "success");
  } catch (error) {
    setBanner((error as Error).message, "error");
    throw error;
  } finally {
    isSubmitting.value = false;
  }
}

async function runSearchOnly(mode: "full" | "search") {
  const keywords = parseKeywords();
  if (keywords.length === 0) {
    setBanner("请至少输入一个关键词", "error");
    return;
  }
  const payload: TaskCreatePayload = {
    task_type: "search_only",
    keywords,
    per_keyword_limit: normalizedPerKeywordLimit(),
    headless: true,
  };
  clearPreviewState();
  await submitTask(payload, mode === "full" ? "搜索预览任务已提交" : "搜索导出任务已提交");
}

async function continueWithPreviewGrab() {
  if (activePreviewItems.value.length === 0) {
    setBanner("当前没有可继续抓取的预览结果", "error");
    return;
  }
  const selectedPreviewItems = activePreviewItems.value.filter((item) => previewSelections.value[previewItemKey(item)]);
  if (selectedPreviewItems.length === 0) {
    setBanner("请至少勾选一条预览结果再继续抓取", "error");
    return;
  }
  if (!form.tableName.trim()) {
    setBanner("请选择或输入目标表名", "error");
    return;
  }
  const items = selectedPreviewItems.map((item) => ({
    detail_url: item.detail_url,
    code: item.code ?? "",
    name: item.name ?? "",
    keyword: item.keyword ?? "search",
  }));
  await submitTask(
    {
      task_type: "direct_grab",
      table_name: form.tableName.trim(),
      duplicate_policy: form.duplicatePolicy,
      items,
      headless: true,
    },
    "抓取任务已提交",
  );
}

async function downloadAllPdf() {
  if (downloadablePdfItems.value.length === 0) {
    setBanner("当前任务没有可下载 PDF", "error");
    return;
  }
  isBulkDownloading.value = true;
  try {
    for (const item of downloadablePdfItems.value) {
      if (!item.pdf_download_url) {
        continue;
      }
      await downloadApiFile(item.pdf_download_url, pdfFallbackName(item));
      await delay(250);
    }
    setBanner(`已开始批量下载 ${downloadablePdfItems.value.length} 个 PDF，如浏览器提示请允许多文件下载`, "success");
  } catch (error) {
    setBanner((error as Error).message, "error");
  } finally {
    isBulkDownloading.value = false;
  }
}

async function downloadArtifact(url: string, key: string) {
  try {
    const fileName = await downloadApiFile(url, artifactFallbackName(key));
    setBanner(`已下载 ${fileName}`, "success");
  } catch (error) {
    setBanner((error as Error).message, "error");
  }
}

async function downloadPdf(item: TaskItem) {
  if (!item.pdf_download_url) {
    return;
  }
  try {
    const fileName = await downloadApiFile(item.pdf_download_url, pdfFallbackName(item));
    setBanner(`已下载 ${fileName}`, "success");
  } catch (error) {
    setBanner((error as Error).message, "error");
  }
}

async function runDirectGrabFromExcel() {
  if (!form.tableName.trim()) {
    setBanner("请选择或输入目标表名", "error");
    return;
  }
  if (excelItems.value.length === 0) {
    setBanner("请先上传 Excel 文件", "error");
    return;
  }
  await submitTask(
    {
      task_type: "direct_grab",
      table_name: form.tableName.trim(),
      duplicate_policy: form.duplicatePolicy,
      items: excelItems.value,
      headless: true,
    },
    "Excel 抓取任务已提交",
  );
}

async function runDirectGrabFromUrls() {
  if (!form.tableName.trim()) {
    setBanner("请选择或输入目标表名", "error");
    return;
  }
  if (detectedUrlCount.value === 0) {
    setBanner("没有识别到有效的详情页链接", "error");
    return;
  }
  await submitTask(
    {
      task_type: "direct_grab",
      table_name: form.tableName.trim(),
      duplicate_policy: form.duplicatePolicy,
      url_text: form.urlText,
      headless: true,
    },
    "URL 批量抓取任务已提交",
  );
}

async function cancelActiveTask() {
  if (!activeTaskId.value) {
    return;
  }
  isCancelling.value = true;
  try {
    await cancelTask(activeTaskId.value);
    await loadTask(activeTaskId.value, true);
    setBanner("已发送取消请求", "success");
  } catch (error) {
    setBanner((error as Error).message, "error");
  } finally {
    isCancelling.value = false;
  }
}

async function loadRecentTask(taskId: string) {
  stopPolling();
  try {
    await loadTask(taskId, true);
    setBanner(`已载入任务 ${taskId}`, "success");
  } catch (error) {
    setBanner((error as Error).message, "error");
  }
}

async function handleExcelChange(event: Event) {
  const target = event.target as HTMLInputElement;
  const [file] = Array.from(target.files ?? []);
  if (!file) {
    return;
  }

  try {
    const buffer = await file.arrayBuffer();
    const workbook = XLSX.read(buffer, { type: "array" });
    const firstSheet = workbook.Sheets[workbook.SheetNames[0]];
    const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(firstSheet, { defval: "" });
    const items = rows
      .map((row) => ({
        detail_url: String(row.detail_url ?? "").trim(),
        code: String(row.code ?? "").trim(),
        name: String(row.name ?? "").trim(),
        keyword: String(row.keyword ?? "").trim() || "excel_upload",
      }))
      .filter((row) => row.detail_url);

    if (items.length === 0) {
      throw new Error("Excel 文件中没有可用的 detail_url 列数据");
    }

    excelItems.value = items;
    form.excelFileName = `${file.name} | ${items.length} 条记录`;
    setBanner(`Excel 解析成功，共 ${items.length} 条记录`, "success");
  } catch (error) {
    excelItems.value = [];
    form.excelFileName = "";
    setBanner((error as Error).message, "error");
  } finally {
    target.value = "";
  }
}

onMounted(() => {
  loadRecentTasks();
  if (getApiToken()) {
    void refreshTables();
  } else {
    setBanner("请输入 worker API token 后再刷新表名", "info");
  }
});

onBeforeUnmount(() => {
  stopPolling();
});
</script>

<template>
  <div class="shell">
    <header class="hero">
      <div>
        <p class="eyebrow">GB CRAWLER WEB CONSOLE</p>
        <h1>国标抓取控制台</h1>
        <p class="subtitle">
          面向浏览器的操作页面，直接复用现有 Python worker，覆盖搜索预览、抓取入库、任务轮询和产物下载。
        </p>
      </div>
      <div class="hero-metrics">
        <div class="metric-card">
          <span>数据库表</span>
          <strong>{{ tables.length }}</strong>
        </div>
        <div class="metric-card">
          <span>最近任务</span>
          <strong>{{ recentTaskIds.length }}</strong>
        </div>
      </div>
    </header>

    <main class="layout">
      <section class="panel command-panel">
        <div class="panel-head">
          <div>
            <h2>任务面板</h2>
            <p>按桌面 GUI 的核心流程拆成四条业务路径。</p>
          </div>
          <button class="ghost-btn" :disabled="isLoadingTables" @click="refreshTables">
            {{ isLoadingTables ? "刷新中..." : "刷新表名" }}
          </button>
        </div>

        <div class="auth-bar">
          <label class="field token-field">
            <span>API token</span>
            <input
              v-model="apiTokenInput"
              type="password"
              autocomplete="off"
              placeholder="输入当前 worker token"
              @keyup.enter="applyApiToken"
            />
          </label>
          <button class="ghost-btn" type="button" @click="applyApiToken">{{ apiTokenButtonLabel }}</button>
        </div>

        <div class="global-grid">
          <label class="field">
            <span>目标表名</span>
            <select
              :value="tables.includes(form.tableName) ? form.tableName : ''"
              @change="form.tableName = ($event.target as HTMLSelectElement).value"
            >
              <option value="" disabled>{{ tables.length > 0 ? "选择已有爬虫业务表" : "暂无兼容表，请输入新表名" }}</option>
              <option v-for="table in tables" :key="`select-${table}`" :value="table">{{ table }}</option>
            </select>
            <small>推荐使用爬虫自己的业务表；如输入新表名，系统会按标准结构自动创建，不建议写入 GeoAI 历史元数据表。</small>
            <input v-model="form.tableName" placeholder="输入新业务表名，默认使用 gb_standards" />
          </label>

          <label class="field">
            <span>重复策略</span>
            <select v-model="form.duplicatePolicy">
              <option value="overwrite">覆盖已有数据</option>
              <option value="skip">跳过已有数据</option>
            </select>
          </label>
        </div>

        <div class="tabs">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            class="tab-btn"
            :class="{ active: activeTab === tab.key }"
            @click="activeTab = tab.key"
          >
            <span>{{ tab.label }}</span>
            <small>{{ tab.caption }}</small>
          </button>
        </div>

        <div class="tab-panel">
          <template v-if="activeTab === 'full' || activeTab === 'search'">
            <div class="form-grid">
              <label class="field span-2">
                <span>关键词</span>
                <textarea
                  v-model="form.keywordsText"
                  rows="5"
                  placeholder="多个关键词可用顿号、逗号、空格或分号分隔"
                />
              </label>
              <label class="field">
                <span>每关键词数量限制</span>
                <input v-model="form.perKeywordLimit" placeholder="留空表示全部命中结果" />
              </label>
            </div>

            <div class="action-row">
              <button class="primary-btn" :disabled="isSubmitting" @click="runSearchOnly(activeTab)">
                {{ isSubmitting ? "提交中..." : activeTab === "full" ? "开始搜索预览" : "导出搜索结果" }}
              </button>
              <button
                v-if="activeTab === 'full'"
                class="accent-btn"
                :disabled="isSubmitting || !previewReady || previewSelectedCount === 0"
                @click="continueWithPreviewGrab"
              >
                用当前预览结果继续抓取
              </button>
            </div>

            <div v-if="activeTab === 'full' && previewReady" class="detail-block preview-block">
              <div class="detail-head">
                <div>
                  <h3>预览结果</h3>
                  <p>默认全部勾选。取消勾选的条目不会进入后续抓取。</p>
                </div>
                <div class="selection-toolbar">
                  <label class="checkbox-pill">
                    <input
                      type="checkbox"
                      :checked="previewAllSelected"
                      :indeterminate.prop="previewPartiallySelected"
                      @change="setAllPreviewSelections(($event.target as HTMLInputElement).checked)"
                    />
                    <span>全选</span>
                  </label>
                  <button class="ghost-btn compact-btn" type="button" @click="setAllPreviewSelections(true)">全选</button>
                  <button class="ghost-btn compact-btn" type="button" @click="setAllPreviewSelections(false)">全不选</button>
                  <span class="selection-summary">已选 {{ previewSelectedCount }} / {{ activePreviewItems.length }}</span>
                </div>
              </div>

              <div class="table-shell">
                <table>
                  <thead>
                    <tr>
                      <th class="checkbox-col">选择</th>
                      <th>编号</th>
                      <th>名称</th>
                      <th>关键词</th>
                      <th>详情页</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="item in activePreviewItems" :key="item.id">
                      <td class="checkbox-col">
                        <input
                          type="checkbox"
                          :checked="previewSelections[previewItemKey(item)] ?? true"
                          @change="updatePreviewSelection(item, ($event.target as HTMLInputElement).checked)"
                        />
                      </td>
                      <td>{{ item.code || "-" }}</td>
                      <td>{{ item.name || "-" }}</td>
                      <td>{{ item.keyword || "-" }}</td>
                      <td>
                        <a :href="item.detail_url" target="_blank" rel="noreferrer">打开</a>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </template>

          <template v-else-if="activeTab === 'excel'">
            <div class="upload-card">
              <label class="upload-zone">
                <input type="file" accept=".xlsx,.xls" @change="handleExcelChange" />
                <span>上传待抓取 Excel</span>
                <small>表格至少要包含 detail_url 列，code、name、keyword 为可选列。</small>
              </label>
              <p class="upload-meta">{{ form.excelFileName || "尚未选择文件" }}</p>
            </div>

            <div class="action-row">
              <button class="primary-btn" :disabled="isSubmitting" @click="runDirectGrabFromExcel">
                {{ isSubmitting ? "提交中..." : "提交 Excel 抓取任务" }}
              </button>
            </div>
          </template>

          <template v-else>
            <label class="field">
              <span>URL 自由文本</span>
              <textarea
                v-model="form.urlText"
                rows="8"
                placeholder="粘贴任意文本，系统会自动提取 std.samr.gov.cn 详情页链接"
              />
            </label>
            <div class="hint-row">
              <span>已识别 {{ detectedUrlCount }} 个有效详情页链接</span>
            </div>
            <div class="action-row">
              <button class="primary-btn" :disabled="isSubmitting" @click="runDirectGrabFromUrls">
                {{ isSubmitting ? "提交中..." : "提交 URL 批量抓取任务" }}
              </button>
            </div>
          </template>
        </div>

        <div v-if="message" class="banner" :class="messageTone">
          {{ message }}
        </div>
      </section>

      <aside class="panel sidebar">
        <div class="panel-head">
          <div>
            <h2>最近任务</h2>
            <p>保存在浏览器本地，刷新页面后仍可继续查看。</p>
          </div>
        </div>
        <div class="recent-list">
          <button
            v-for="taskId in recentTaskIds"
            :key="taskId"
            class="recent-task"
            @click="loadRecentTask(taskId)"
          >
            <strong>{{ taskId.slice(0, 8) }}</strong>
            <span>{{ taskId }}</span>
          </button>
          <p v-if="recentTaskIds.length === 0" class="muted">暂无历史任务。</p>
        </div>
      </aside>

      <section class="panel result-panel">
        <div class="panel-head">
          <div>
            <h2>任务结果</h2>
            <p>轮询状态、结果摘要、产物下载和逐条记录都集中在这里。</p>
          </div>
          <div class="toolbar">
            <span v-if="activeTaskId" class="task-chip">{{ activeTaskId }}</span>
            <button class="ghost-btn" :disabled="!activeTaskId || isCancelling" @click="cancelActiveTask">
              {{ isCancelling ? "取消中..." : "取消任务" }}
            </button>
          </div>
        </div>

        <template v-if="activeTaskResult">
          <div class="summary-grid">
            <article class="summary-card">
              <span>任务状态</span>
              <strong>{{ activeTaskResult.status }}</strong>
            </article>
            <article class="summary-card" v-if="activeSummary">
              <span>总数</span>
              <strong>{{ activeSummary.total }}</strong>
            </article>
            <article class="summary-card" v-if="activeSummary">
              <span>成功</span>
              <strong>{{ activeSummary.succeeded }}</strong>
            </article>
            <article class="summary-card" v-if="activeSummary">
              <span>失败</span>
              <strong>{{ activeSummary.failed }}</strong>
            </article>
          </div>

          <div v-if="activeSearchSummary" class="detail-block">
            <h3>搜索摘要</h3>
            <p>
              关键词：{{ activeSearchSummary.keywords.join("、") || "无" }}；
              每关键词限制：{{ activeSearchSummary.per_keyword_limit ?? "全部" }}；
              原始命中：{{ activeSearchSummary.raw_count }}；
              去重后待抓取：{{ activeSearchSummary.deduplicated_count }}
            </p>
          </div>

          <div v-if="Object.keys(activeArtifacts).length > 0" class="detail-block">
            <h3>产物下载</h3>
            <div class="download-list">
              <button
                v-for="(url, key) in activeArtifacts"
                :key="key"
                class="download-link"
                type="button"
                @click="downloadArtifact(String(url), String(key))"
              >
                下载 {{ key }}
              </button>
            </div>
          </div>

          <div v-if="activeDownloadSummary" class="detail-block">
            <h3>下载摘要</h3>
            <p>
              已跟踪条目：{{ activeDownloadSummary.tracked_items }}；
              已保存 PDF：{{ activeDownloadSummary.pdf_saved }}；
              已解析下载链接：{{ activeDownloadSummary.download_url_resolved }}
            </p>
          </div>

          <div v-if="activeErrors.length > 0" class="detail-block">
            <h3>错误摘要</h3>
            <ul class="error-list">
              <li v-for="item in activeErrors" :key="`${item.detail_url}-${item.message}`">
                <strong>{{ item.code || "未知编号" }}</strong>
                <span>{{ item.message }}</span>
              </li>
            </ul>
          </div>

          <div class="detail-block">
            <div class="detail-head">
              <div>
                <h3>任务明细</h3>
                <p>成功条目可单独下载 PDF，也可以一次性触发当前任务的全部 PDF 下载。</p>
              </div>
              <button
                class="ghost-btn compact-btn"
                type="button"
                :disabled="isBulkDownloading || downloadablePdfItems.length === 0"
                @click="downloadAllPdf"
              >
                {{ isBulkDownloading ? "批量下载中..." : `下载全部 PDF（${downloadablePdfItems.length}）` }}
              </button>
            </div>
            <div class="table-shell">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>编号</th>
                    <th>名称</th>
                    <th>状态</th>
                    <th>详情页</th>
                    <th>PDF</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="item in activeTaskResult.items" :key="item.id">
                    <td>{{ item.id }}</td>
                    <td>{{ item.code || "-" }}</td>
                    <td>{{ item.name || "-" }}</td>
                    <td>{{ item.item_status }}</td>
                    <td>
                      <a :href="item.detail_url" target="_blank" rel="noreferrer">打开</a>
                    </td>
                    <td>
                      <button
                        v-if="item.pdf_download_url"
                        class="text-link"
                        type="button"
                        @click="downloadPdf(item)"
                      >
                        下载 PDF
                      </button>
                      <span v-else>-</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>

        <p v-else class="muted">提交任务后，这里会显示状态、摘要和产物链接。</p>
      </section>
    </main>
  </div>
</template>
