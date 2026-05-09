# Docker Deployment

## Purpose

Package the worker service as a headless Docker container so the crawler can run as an AI-callable execution engine on a local machine or server.

This deployment target is for the worker HTTP service only. The legacy GUI remains a separate local debugging entrypoint and is not part of the container runtime.

## Files

- `Dockerfile`
- `docker-compose.yml`
- `.env.example`
- `docker/start-worker.sh`

## Worker API

- `GET /health`
- `POST /tasks`
- `GET /tasks/{task_id}`
- `GET /tasks/{task_id}/result`
- `POST /tasks/{task_id}/cancel`

## First Run

1. Create an environment file.

```bash
cp .env.example .env
```

2. Fill in the required settings.

- `STD_DB_HOST`
- `STD_DB_PORT`
- `STD_DB_USER`
- `STD_DB_PASSWORD`
- `STD_DB_DATABASE`
- `STD_CHAOJIYING_USER`
- `STD_CHAOJIYING_PASS`
- `STD_CHAOJIYING_SOFTID`

Notes:

- On Docker Desktop, `STD_DB_HOST=host.docker.internal` is the usual choice when MySQL is on the host.
- On Linux servers, point `STD_DB_HOST` to the actual reachable host or container address.

3. Build and start the worker.

```bash
docker compose --env-file .env build
docker compose --env-file .env up -d
```

4. Verify health.

```bash
curl http://127.0.0.1:8765/health
```

Expected response:

```json
{"status":"ok"}
```

## Minimal Smoke Task

Submit a single `direct_grab` task:

```bash
curl -X POST http://127.0.0.1:8765/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "direct_grab",
    "table_name": "standard_norm_detail_test",
    "headless": true,
    "items": [
      {
        "code": "GB 45438-2025",
        "name": "网络安全技术 人工智能生成合成内容标识方法",
        "detail_url": "https://std.samr.gov.cn/gb/search/gbDetailed?id=301E0388CB75788DE06397BE0A0AE1B4",
        "keyword": "人工智能"
      }
    ]
  }'
```

Check task state:

```bash
curl http://127.0.0.1:8765/tasks/<task_id>
curl http://127.0.0.1:8765/tasks/<task_id>/result
```

## Artifacts

The container mounts these paths back to the host:

- `./artifacts`
- `./.tmp`

For task inspection, check:

- `artifacts/tasks/<task_id>/task.log`
- `artifacts/tasks/<task_id>/pdf/`
- `artifacts/tasks/<task_id>/debug/`

## Resource Limits

`docker-compose.yml` configures:

- `cpus: 1.0`
- `mem_limit: 2g`
- `shm_size: 1gb`
- `restart: unless-stopped`
- `no-new-privileges:true`

## Current Stage

- The worker service is the primary runtime for AI or agent invocation.
- The local GUI is still available for manual debugging.
- A browser-based manual operations UI is a future direction and is not implemented in this repository yet.
