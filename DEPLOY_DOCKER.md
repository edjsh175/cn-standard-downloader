# Docker Deployment

## Purpose

Package the worker service and the browser-based control panel into one Docker deployment so the crawler can run on a local machine or server.

This deployment target includes:

- The Python worker HTTP service
- The Vue3 web console served by the same process

The legacy GUI remains a separate local debugging entrypoint and is not part of the container runtime.

## Files

- `Dockerfile`
- `docker-compose.yml`
- `.env.example`
- `.env.prod.example`
- `.env.test.example`
- `docker/start-worker.sh`

## Runtime Entry

After deployment:

- `GET /health` and `GET /api/health` are health checks
- `/` serves the web console
- `/api/*` serves the browser-facing API
- Legacy `/tasks/*` endpoints remain available for compatibility

## Worker API

- `GET /health`
- `GET /api/health`
- `GET /api/tables`
- `POST /tasks`
- `POST /api/tasks`
- `GET /tasks/{task_id}`
- `GET /api/tasks/{task_id}`
- `GET /tasks/{task_id}/result`
- `GET /api/tasks/{task_id}/result`
- `POST /tasks/{task_id}/cancel`
- `POST /api/tasks/{task_id}/cancel`

Additional browser-facing download routes:

- `GET /api/tasks/{task_id}/artifacts/search_results`
- `GET /api/tasks/{task_id}/artifacts/failed_results`
- `GET /api/tasks/{task_id}/artifacts/log_file`
- `GET /api/tasks/{task_id}/items/{item_id}/pdf`

Current task types:

- `search_only`
- `keyword_search`
- `direct_grab`

## Deployment Model

This repository supports running two isolated worker instances from the same code directory:

- Production: long-running, externally reachable, uses the production database.
- Test: started only when needed, bound to `127.0.0.1`, uses a separate test database.

Isolation relies on all of the following:

- Different Compose project names
- Different environment files
- Different host ports
- Different host artifact and temp directories
- Different database names

Do not reuse the same database name, host artifact directory, or host temp directory across prod and test.

## First Run

1. Pull the repository source code onto the target machine.

```bash
git clone <your-repo-url>
cd <repo-dir>
```

2. Create environment files from the templates.

```bash
cp .env.prod.example .env.prod
cp .env.test.example .env.test
```

3. Fill in the required settings in both files.

- `STD_DB_HOST`
- `STD_DB_PORT`
- `STD_DB_USER`
- `STD_DB_PASSWORD`
- `STD_DB_DATABASE`
- `STD_CHAOJIYING_USER`
- `STD_CHAOJIYING_PASS`
- `STD_CHAOJIYING_SOFTID`
- `STD_BIND_IP`
- `STD_WORKER_PORT`
- `STD_WORKER_API_TOKEN`
- `STD_ALLOW_INSECURE_BROWSER_FLAGS`（默认 `false`；仅在明确的兼容性排障场景临时开启）
- `STD_ALLOW_BROWSER_REMOTE_DEBUGGING`（默认 `false`；不要在公网暴露 9222）
- `STD_ARTIFACTS_DIR`
- `STD_TMP_DIR`
- `STD_WEB_BASE_PATH`
- `STD_WEB_API_BASE_PATH`

Required isolation defaults:

- Production `STD_DB_DATABASE=disaster_knowledge`
- Test `STD_DB_DATABASE=disaster_knowledge_test`
- Production `STD_BIND_IP=0.0.0.0`
- Test `STD_BIND_IP=127.0.0.1`
- Production `STD_WORKER_PORT=8765`
- Test `STD_WORKER_PORT=8766`
- Production `STD_ARTIFACTS_DIR=./artifacts-prod`
- Test `STD_ARTIFACTS_DIR=./artifacts-test`
- Production `STD_TMP_DIR=./.tmp-prod`
- Test `STD_TMP_DIR=./.tmp-test`
- Production `STD_WEB_BASE_PATH=/crawler/`
- Production `STD_WEB_API_BASE_PATH=/crawler/api`
- Test `STD_WEB_BASE_PATH=/`
- Test `STD_WEB_API_BASE_PATH=/api`

Notes:

- On Docker Desktop, `STD_DB_HOST=host.docker.internal` is the usual choice when MySQL is on the host.
- On Linux servers, point `STD_DB_HOST` to the actual reachable host or container address.
- The test instance is intentionally bound to `127.0.0.1` so it is only reachable from the server itself.
- The image is built locally from this repository. You do not need to manually clone any application image from a registry.
- Docker will still pull base images required by the `Dockerfile` during the build if they do not already exist on the machine.
- The web console does not receive `STD_WORKER_API_TOKEN` during image build. Enter the worker token in the browser at runtime; it is stored only for the current browser session.

## Start Production

Build and start the long-running production service:

```bash
docker compose -p std-worker-prod --env-file .env.prod up -d --build
```

Verify health:

```bash
curl http://127.0.0.1:8765/health
```

If production is exposed publicly, external callers can use `http://<server-ip>:8765/health`.

Expected response:

```json
{"status":"ok"}
```

Open the web console:

- Local on the server: `http://127.0.0.1:8765/`
- Remote browser: `http://<server-ip>:8765/`

## Start Test

Build and start the isolated test service only when needed:

```bash
docker compose -p std-worker-test --env-file .env.test up -d --build
```

Verify test health on the server itself:

```bash
curl http://127.0.0.1:8766/health
```

The test instance is not intended to be reachable from external machines.

Open the test web console on the server itself:

- `http://127.0.0.1:8766/`

## Check Status

Inspect both environments:

```bash
docker compose -p std-worker-prod --env-file .env.prod ps
docker compose -p std-worker-test --env-file .env.test ps
```

You can also confirm both containers at once with:

```bash
docker ps --filter "name=std-worker"
```

## Stop Test

Stop and remove only the test environment:

```bash
docker compose -p std-worker-test --env-file .env.test down
```

This does not affect the production environment.

## Minimal Smoke Task

Submit a single `direct_grab` task to the target instance:

```bash
TOKEN="<worker-token>"
curl -X POST http://127.0.0.1:<worker-port>/tasks \
  -H "Authorization: Bearer ${TOKEN}" \
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
curl -H "Authorization: Bearer ${TOKEN}" http://127.0.0.1:<worker-port>/tasks/<task_id>
curl -H "Authorization: Bearer ${TOKEN}" http://127.0.0.1:<worker-port>/tasks/<task_id>/result
```

Minimal search preview smoke task:

```bash
curl -X POST http://127.0.0.1:<worker-port>/api/tasks \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "search_only",
    "keywords": ["人工智能"],
    "per_keyword_limit": 5
  }'
```

Browser smoke check:

1. Open `http://127.0.0.1:<worker-port>/`
2. Enter the current `STD_WORKER_API_TOKEN`
3. Confirm the table list can be fetched
4. Submit a `search_only` task from the page

## Artifacts

The container mounts these paths back to the host:

- `STD_ARTIFACTS_DIR`
- `STD_TMP_DIR`

For task inspection, check:

- `<artifacts-dir>/tasks/<task_id>/task.log`
- `<artifacts-dir>/tasks/<task_id>/pdf/`
- `<artifacts-dir>/tasks/<task_id>/debug/`

## Resource Limits

`docker-compose.yml` configures:

- `cpus: 1.0`
- `mem_limit: 2g`
- `shm_size: 1gb`
- `restart: unless-stopped`
- `no-new-privileges:true`

## Current Stage

- The worker service is the primary runtime for AI or agent invocation.
- The web console is available for browser-based manual operation.
- The local GUI is still available for manual debugging.

## Long-Term Constraints

- Production and test can share the same code checkout.
- Production and test must not share the same database name.
- Production and test must not share the same host artifact directory.
- Production and test must not share the same host temp directory.
- Business table names may be the same across prod and test because database isolation keeps them separate.
