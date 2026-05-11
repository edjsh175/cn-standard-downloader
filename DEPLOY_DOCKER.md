# Docker Deployment

## Purpose

Package the worker service as a headless Docker container so the crawler can run as an AI-callable execution engine on a local machine or server.

This deployment target is for the worker HTTP service only. The legacy GUI remains a separate local debugging entrypoint and is not part of the container runtime.

## Files

- `Dockerfile`
- `docker-compose.yml`
- `.env.example`
- `.env.prod.example`
- `.env.test.example`
- `docker/start-worker.sh`

## Worker API

- `GET /health`
- `POST /tasks`
- `GET /tasks/{task_id}`
- `GET /tasks/{task_id}/result`
- `POST /tasks/{task_id}/cancel`

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

1. Create environment files from the templates.

```bash
cp .env.prod.example .env.prod
cp .env.test.example .env.test
```

2. Fill in the required settings in both files.

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
- `STD_ARTIFACTS_DIR`
- `STD_TMP_DIR`

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

Notes:

- On Docker Desktop, `STD_DB_HOST=host.docker.internal` is the usual choice when MySQL is on the host.
- On Linux servers, point `STD_DB_HOST` to the actual reachable host or container address.
- The test instance is intentionally bound to `127.0.0.1` so it is only reachable from the server itself.

## Start Production

Build and start the long-running production worker:

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

## Start Test

Build and start the isolated test worker only when needed:

```bash
docker compose -p std-worker-test --env-file .env.test up -d --build
```

Verify test health on the server itself:

```bash
curl http://127.0.0.1:8766/health
```

The test instance is not intended to be reachable from external machines.

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
curl -X POST http://127.0.0.1:<worker-port>/tasks \
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
curl http://127.0.0.1:<worker-port>/tasks/<task_id>
curl http://127.0.0.1:<worker-port>/tasks/<task_id>/result
```

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
- The local GUI is still available for manual debugging.
- A browser-based manual operations UI is a future direction and is not implemented in this repository yet.

## Long-Term Constraints

- Production and test can share the same code checkout.
- Production and test must not share the same database name.
- Production and test must not share the same host artifact directory.
- Production and test must not share the same host temp directory.
- Business table names may be the same across prod and test because database isolation keeps them separate.
