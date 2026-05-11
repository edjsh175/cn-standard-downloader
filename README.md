# 国标爬虫

国标爬虫正在从“本地人工下载器”演进为“可被 AI 调用的执行引擎”。

当前主入口是 HTTP worker 服务，适合被 agent、自动化流程或其他系统调用。历史上的本地 GUI 仍然保留，用于人工调试和兼容旧使用方式。网页手动操作入口是后续方向，本仓库当前不宣称已实现。

## 当前定位

- 主入口：`run_worker.py` / `app.worker_service`
- 兼容入口：`gui_main.py`
- 后续方向：网页手动操作入口

## Worker API

- `GET /health`
- `POST /tasks`
- `GET /tasks/{task_id}`
- `GET /tasks/{task_id}/result`
- `POST /tasks/{task_id}/cancel`

当前支持的任务类型：

- `keyword_search`
- `direct_grab`

## Repository Layout

- `app/`: worker service, task pipeline, and task state storage
- `grab_module.py`: Selenium-based crawl, download, and database write flow
- `search_module.py`: keyword-driven standard discovery
- `utils.py`: browser bootstrap and shared runtime helpers
- `config.py`: unified runtime configuration for GUI and worker modes
- `docker/`, `Dockerfile`, `docker-compose.yml`: headless worker deployment assets

## Quick Start

### 1. Local GUI debugging

Use `gui_main.py` when you need manual local debugging or to keep the legacy workflow available.

### 2. Worker service

Run the AI-callable worker locally:

```bash
python run_worker.py
```

Health check:

```bash
curl http://127.0.0.1:8765/health
```

### 3. Docker worker

See [DEPLOY_DOCKER.md](DEPLOY_DOCKER.md) for the containerized headless deployment flow.

## Current Stage

- The agent worker path is the primary focus.
- Database write idempotency is handled by unique business keys plus upsert semantics.
- Task tracking supports per-item status, result retrieval, and cancellation.
- The repository still contains the local GUI because debugging is not fully agent-only yet.

## Notes

- Runtime state such as `.env`, `config_user.json`, `artifacts/`, `.tmp/`, and temporary captcha files should remain local and are ignored by git.
- The checked-in driver asset is intended to support local browser automation without depending on a fresh driver download in every environment.
