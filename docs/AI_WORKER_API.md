# AI Worker API

本文档定义 AI/agent 调用本项目的推荐方式。桌面 GUI 和 Web console 仍然存在，但 AI 调用应以 HTTP worker 为稳定入口。

## 入口

- 健康检查：`GET /health`、`GET /api/health`
- 能力发现：`GET /api/capabilities`
- 创建任务：`POST /api/tasks`
- 查询任务：`GET /api/tasks/{task_id}`
- 查询结果：`GET /api/tasks/{task_id}/result`
- 取消任务：`POST /api/tasks/{task_id}/cancel`
- 下载 artifact：`GET /api/tasks/{task_id}/artifacts/{artifact_name}`
- 下载 PDF：`GET /api/tasks/{task_id}/items/{item_id}/pdf`

除健康检查和 Web 静态页面外，API 请求都需要：

```http
Authorization: Bearer <STD_WORKER_API_TOKEN>
```

## 推荐 AI 工作流

1. 调用 `GET /api/capabilities`，确认 worker 支持的任务类型、终态、artifact 名称和推荐流程。
2. 用 `search_only` 搜索候选标准：

```json
{
  "task_type": "search_only",
  "keywords": ["人工智能"],
  "per_keyword_limit": 5
}
```

3. 轮询 `GET /api/tasks/{task_id}`，直到 `agent_status.terminal == true`。
4. 如果 `agent_status.outcome == "results_available"`，调用 `/result` 获取 `items`。
5. 从 `items` 中选择要抓取的条目，再提交 `direct_grab`：

```json
{
  "task_type": "direct_grab",
  "table_name": "gb_standards",
  "duplicate_policy": "overwrite",
  "headless": true,
  "items": [
    {
      "detail_url": "https://std.samr.gov.cn/gb/search/gbDetailed?id=...",
      "code": "GB/T 1.1-2020",
      "name": "标准化工作导则 第1部分：标准化文件的结构和起草规则",
      "keyword": "GB/T 1.1-2020"
    }
  ]
}
```

6. 轮询抓取任务；终态后根据 `agent_status` 决定下载 PDF、下载失败清单、重试或换候选标准。

## agent_status

所有任务详情和任务结果响应都会包含 `agent_status`：

```json
{
  "lifecycle": "succeeded",
  "terminal": true,
  "outcome": "results_available",
  "retryable": false,
  "error_code": null,
  "next_actions": ["fetch_result", "select_items_for_direct_grab", "download_artifacts"]
}
```

字段含义：

- `lifecycle`：底层任务状态，如 `pending`、`running`、`succeeded`、`failed`。
- `terminal`：是否为终态。
- `outcome`：AI 应理解的业务结果。
- `retryable`：是否值得在修复环境或稍后重试。
- `error_code`：稳定英文错误码。
- `next_actions`：建议 AI 下一步动作。

常见 `outcome`：

- `pending`：继续轮询。
- `results_available`：搜索有候选，下一步选择 items 后抓取。
- `no_results`：搜索无结果，换关键词。
- `downloaded`：抓取成功，可下载 PDF/artifacts。
- `partial_downloaded`：部分成功，检查 errors 和 failed_results。
- `blocked_captcha`：验证码平台或验证码识别阻塞。
- `not_public`：标准没有公开文本/PDF 入口或受权限限制。
- `failed`：其他失败，查看 `errors` 和 `task.log`。

## 错误码

`result.errors[]` 会保留原有 `error_type` 和 `message`，并新增：

```json
{
  "error_code": "CAPTCHA_NO_BALANCE",
  "retryable": true
}
```

稳定错误码：

- `CAPTCHA_NO_BALANCE`：验证码平台无可用题分，需要充值或更换账号。
- `CAPTCHA_FAILED`：验证码识别或提交失败，可以重试。
- `NO_PUBLIC_TEXT`：没有查看文本/PDF 入口，换候选标准。
- `PDF_DOWNLOAD_FAILED`：PDF 下载失败，可以稍后重试。
- `DB_WRITE_FAILED`：数据库写入失败，先修复数据库配置或表结构。
- `SITE_TIMEOUT`：站点或页面元素超时，可以重试。
- `INVALID_INPUT`：请求参数无效，修正 payload。
- `UNKNOWN_ERROR`：未分类失败，查看 `task.log` 和 debug artifacts。

## 测试脚本

默认 smoke 不访问真实国标站、不调用验证码：

```powershell
.\.venv\Scripts\python.exe scripts\ai_worker_smoke.py --base-url http://127.0.0.1:8766 --token test-worker-token
```

默认检查：

- `/health` 可达。
- `/api/capabilities` 无 token 返回 `401`。
- `/api/capabilities` 带 token 返回 contract 元数据。
- 本地 contract 示例能正确映射 search/direct/captcha 场景。

真实搜索必须显式启用：

```powershell
.\.venv\Scripts\python.exe scripts\ai_worker_smoke.py --base-url http://127.0.0.1:8766 --token test-worker-token --real-search-keyword "人工智能"
```

真实验证码/PDF 下载不进入默认测试；如果验证码平台返回 `无可用题分`，应记录为 `CAPTCHA_NO_BALANCE` 外部阻塞，而不是代码通过。
