# 国标爬虫

国标爬虫正在从“本地人工下载器”演进为“可被 AI 调用的执行引擎”。

当前主入口是 HTTP worker 服务 + Web console。worker 适合被 agent、自动化流程或其他系统调用；Web console 复用同一个 worker API，提供浏览器内的人工操作入口。历史上的本地 GUI 仍然保留，但定位为兼容和调试入口。

## 当前定位

- 主入口：`run_worker.py` / `app.worker_service`，以及由 worker 托管的 `web/dist` Web console
- 兼容调试入口：`gui_main.py`
- 前端源码：`web/`

## Worker API

- `GET /health`
- `GET /api/health`
- `POST /tasks`
- `GET /tasks/{task_id}`
- `GET /tasks/{task_id}/result`
- `POST /tasks/{task_id}/cancel`
- `GET /api/tasks/{task_id}/artifacts/{artifact_name}`
- `GET /api/tasks/{task_id}/items/{item_id}/pdf`

除 `GET /health`、`GET /api/health` 和静态 Web console 页面外，worker API 需要 Bearer token：

```bash
export STD_WORKER_API_TOKEN="change-me-worker-token"
curl -H "Authorization: Bearer change-me-worker-token" http://127.0.0.1:8765/api/tables
```

PowerShell:

```powershell
$env:STD_WORKER_API_TOKEN = "change-me-worker-token"
curl.exe -H "Authorization: Bearer change-me-worker-token" http://127.0.0.1:8765/api/tables
```

Web console 不再在构建期写入 worker token。打开页面后输入当前 worker token；浏览器只在当前会话保存 token，并且只把 `Authorization` 发送给配置的 API base 请求。

当前支持的任务类型：

- `keyword_search`
- `direct_grab`
- `search_only`

## Repository Layout

- `app/`: worker service, task pipeline, and task state storage
- `grab_module.py`: Selenium-based crawl, download, and database write flow
- `search_module.py`: keyword-driven standard discovery
- `utils.py`: browser bootstrap and shared runtime helpers
- `config.py`: unified runtime configuration for GUI and worker modes
- `docker/`, `Dockerfile`, `docker-compose.yml`: headless worker deployment assets

## Quick Start

### 1. Worker service + Web console

Build the Web console first:

```bash
cd web
npm install
npm run build
```

Then run the AI-callable worker locally:

```bash
STD_WORKER_API_TOKEN="change-me-worker-token" python run_worker.py
```

PowerShell:

```powershell
$env:STD_WORKER_API_TOKEN = "change-me-worker-token"
python run_worker.py
```

Health check:

```bash
curl http://127.0.0.1:8765/health
```

Open `http://127.0.0.1:8765/` for the Web console.

### 2. Local GUI debugging

Use `gui_main.py` when you need manual local debugging or to keep the legacy workflow available.

### 3. Docker worker

See [DEPLOY_DOCKER.md](DEPLOY_DOCKER.md) for the containerized headless deployment flow.

## Current Stage

- The worker + Web console path is the primary focus.
- Database write idempotency is handled by unique business keys plus upsert semantics.
- Task tracking supports per-item status, result retrieval, and cancellation.
- The repository still contains the local GUI for compatibility and local debugging.

## Notes

- Runtime state such as `.env`, `config_user.json`, `artifacts/`, `.tmp/`, and temporary captcha files should remain local and are ignored by git.
- The checked-in driver asset is intended to support local browser automation without depending on a fresh driver download in every environment.
