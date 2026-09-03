# Agent Tool Runtime v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将国标检索与下载 Worker 固化为上层 Agent 可可靠调用的工具运行时，不引入新的 LLM Agent 层。

**Architecture:** 保留现有 HTTP Worker 和数据库任务存储，增加 typed contract、稳定错误目录、显式任务状态迁移与幂等请求。执行链继续由 `PipelineRunner` 调用现有 search/crawler，但通过可注入的 fake executor 验证 Agent 端到端闭环；数据库升级采用向后兼容的字段迁移，不改变既有 API 的基础路径。

**Tech Stack:** Python 3、标准库 `dataclasses`/`enum`/`hashlib`、MySQL via `pymysql`、现有 `unittest` 测试体系。

---

### Task 1: 建立版本化 Agent Tool Contract

**Files:**
- Create: `app/tool_contract.py`
- Modify: `app/agent_contract.py`
- Modify: `app/worker_service.py`
- Modify: `docs/AI_WORKER_API.md`
- Test: `tests/test_tool_contract.py`
- Test: `tests/test_worker_service.py`

- [ ] **Step 1: Write the failing tests**

  Add tests for `get_tool_contract()` returning `contract_version`, five tool definitions, input limits, error catalog, and artifact metadata; add a worker capability test asserting the same contract is exposed without duplicating a second hand-written list.

- [ ] **Step 2: Run the focused tests to verify they fail**

  Run: `\.venv\Scripts\python.exe -m unittest tests.test_tool_contract -v`
  Expected: FAIL because `app.tool_contract` and `get_tool_contract` do not exist.

- [ ] **Step 3: Implement the minimal contract**

  Define immutable Python dictionaries for `search_standards`, `download_standards`, `get_task_status`, `get_task_result`, `cancel_task`, and `get_artifact`. Include `contract_version`, `api_version`, `limits`, `terminal_states`, `error_catalog`, and artifact fields `name`, `content_type`, `sha256`, `size_bytes`. Make `get_capabilities()` return this contract's public projection.

- [ ] **Step 4: Run focused and regression tests**

  Run: `\.venv\Scripts\python.exe -m unittest tests.test_tool_contract tests.test_agent_contract tests.test_worker_service -v`
  Expected: all focused tests pass and existing contract behavior remains compatible.

- [ ] **Step 5: Update the API documentation and commit**

  Document the canonical tool names, request examples, idempotency behavior, and contract version in `docs/AI_WORKER_API.md`; run the focused tests again, then commit only the P0 contract files.

### Task 2: Replace message inference with typed error creation

**Files:**
- Create: `app/errors.py`
- Modify: `app/agent_contract.py`
- Modify: `app/pipeline.py`
- Modify: `app/worker_service.py`
- Test: `tests/test_errors.py`
- Test: `tests/test_agent_contract.py`

- [ ] **Step 1: Write the failing tests**

  Cover `WorkerError` serialization, category/retryability, preservation of `detail_url`, and a pipeline failure created with an explicit error code rather than inferred from a message. Keep the existing string-classification tests as backward-compatibility tests.

- [ ] **Step 2: Run the focused tests to verify they fail**

  Run: `\.venv\Scripts\python.exe -m unittest tests.test_errors -v`
  Expected: FAIL because typed errors do not exist.

- [ ] **Step 3: Implement the minimal typed error model**

  Add an `ErrorCode` enum, an error catalog containing `retryable` and `category`, and `WorkerError.to_dict()`. Update result aggregation to accept explicit `error_code` when present, while retaining `classify_error_code()` only as a legacy fallback for old persisted results.

- [ ] **Step 4: Run focused and regression tests**

  Run: `\.venv\Scripts\python.exe -m unittest tests.test_errors tests.test_agent_contract tests.test_worker_service -v`
  Expected: all pass.

- [ ] **Step 5: Commit**

  Commit the typed error model and compatibility changes after the tests pass.

### Task 3: Make task lifecycle explicit and restart-aware

**Files:**
- Create: `app/task_state.py`
- Modify: `app/task_store.py`
- Modify: `app/worker_service.py`
- Modify: `app/pipeline.py`
- Test: `tests/test_task_state.py`
- Test: `tests/test_task_store.py`
- Test: `tests/test_worker_service.py`

- [ ] **Step 1: Write the failing tests**

  Test legal and illegal state transitions, `claim_task()` returning a lease, heartbeat extension, recovery of an expired running task, and idempotent duplicate submission by request key using a fake database connection.

- [ ] **Step 2: Run the focused tests to verify they fail**

  Run: `\.venv\Scripts\python.exe -m unittest tests.test_task_state tests.test_task_store -v`
  Expected: FAIL because the state transition and lease methods do not exist.

- [ ] **Step 3: Implement schema-compatible lifecycle support**

  Add a transition table and `assert_transition()`. Extend task-table creation with nullable `idempotency_key`, `lease_owner`, `lease_until`, `heartbeat_at`, `attempt_count`, `timeout_seconds`, and `priority`; add additive migration checks for existing tables. Implement atomic claim/release/heartbeat/recover methods and make duplicate idempotency keys return the existing task id.

- [ ] **Step 4: Wire lifecycle into the worker**

  Claim tasks before execution, heartbeat at stage boundaries, release the lease on all terminal paths, and recover stale tasks on worker startup. Ensure task cancellation remains best-effort but is represented as an explicit terminal transition.

- [ ] **Step 5: Run focused and regression tests**

  Run: `\.venv\Scripts\python.exe -m unittest tests.test_task_state tests.test_task_store tests.test_worker_service tests.test_agent_contract -v`
  Expected: all pass without requiring a live MySQL instance.

- [ ] **Step 6: Commit**

  Commit lifecycle and recovery changes after tests pass.

### Task 4: Add a fake execution path for Agent integration tests

**Files:**
- Create: `app/executor_protocol.py`
- Create: `app/fake_executor.py`
- Modify: `app/pipeline.py`
- Create: `tests/test_agent_flow.py`
- Modify: `scripts/ai_worker_smoke.py`
- Modify: `docs/AI_WORKER_API.md`

- [ ] **Step 1: Write the failing flow tests**

  Exercise search result availability, selection of one candidate, direct download success, partial failure with retryable item error, captcha human-intervention outcome, and cancellation using fake search/download implementations.

- [ ] **Step 2: Run the flow tests to verify they fail**

  Run: `\.venv\Scripts\python.exe -m unittest tests.test_agent_flow -v`
  Expected: FAIL because the executor protocol and fake implementation do not exist.

- [ ] **Step 3: Implement dependency-injected executor boundaries**

  Define protocols for search and download execution, provide deterministic fake scenarios, and let `PipelineRunner` receive executor dependencies with the existing real implementations as defaults. Do not make the fake path reachable from production requests unless explicitly enabled by a test-only constructor.

- [ ] **Step 4: Add deterministic smoke mode**

  Add `--fake-flow` to `scripts/ai_worker_smoke.py`; it must exercise the same contract/status mapping without network, browser, captcha, or database access.

- [ ] **Step 5: Run all tests and smoke mode**

  Run: `\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  Run: `\.venv\Scripts\python.exe scripts\ai_worker_smoke.py --token test-worker-token --fake-flow`
  Expected: all tests pass and smoke output reports a successful fake flow.

- [ ] **Step 6: Commit**

  Commit the injectable execution boundaries, fake flow, and documentation.

### Task 5: Add artifact integrity and structured run evidence

**Files:**
- Create: `app/artifacts.py`
- Modify: `app/pipeline.py`
- Modify: `app/worker_service.py`
- Test: `tests/test_artifacts.py`
- Test: `tests/test_worker_service.py`
- Modify: `docs/AI_WORKER_API.md`

- [ ] **Step 1: Write the failing tests**

  Test artifact metadata generation for a real temporary file, missing-file behavior, safe filename handling, and API responses containing `size_bytes`, `sha256`, and `content_type` without exposing absolute local paths.

- [ ] **Step 2: Run the focused tests to verify they fail**

  Run: `\.venv\Scripts\python.exe -m unittest tests.test_artifacts -v`
  Expected: FAIL because artifact metadata helpers do not exist.

- [ ] **Step 3: Implement metadata and structured run summary**

  Hash files incrementally with SHA-256, infer content type from the controlled artifact name, and add stage timing/item counters to the result payload. Keep physical paths internal and expose only artifact identifiers and metadata.

- [ ] **Step 4: Run the full regression suite**

  Run: `\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  Expected: all tests pass.

- [ ] **Step 5: Commit**

  Commit artifact integrity and run evidence changes after verification.

### Task 6: Security and delivery hardening

**Files:**
- Modify: `app/worker_service.py`
- Modify: `config.py`
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `DEPLOY_DOCKER.md`
- Test: `tests/test_worker_security.py`

- [ ] **Step 1: Write failing security tests**

  Cover request body size limits, JSON/content-type validation, redacted 4xx/5xx responses, absent production token rejection, and artifact streaming/path confinement.

- [ ] **Step 2: Run the focused tests to verify they fail**

  Run: `\.venv\Scripts\python.exe -m unittest tests.test_worker_security -v`
  Expected: FAIL for the newly required protections.

- [ ] **Step 3: Implement minimal protections**

  Add configurable body and item limits, validate content type, return stable public errors with `request_id`, reject unsafe production defaults, and stream controlled artifacts without revealing local paths. Document the captcha HTTP dependency as an explicit deployment risk.

- [ ] **Step 4: Run all tests, smoke checks, and frontend build**

  Run: `\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  Run: `\.venv\Scripts\python.exe scripts\ai_worker_smoke.py --token test-worker-token --fake-flow`
  Run: `npm.cmd run build` in `web`
  Expected: all Python tests pass, fake smoke flow passes, and the frontend build exits with code 0.

- [ ] **Step 5: Review the complete requirement matrix and commit**

  Re-read `docs/ARCHITECTURE_AUDIT_PRD.md`, verify every P0/P1 item addressed by this plan, inspect `git diff --check`, then commit only the implementation files. Keep unrelated user files unstaged.

## Verification matrix

- Agent can complete search → select → download using only the published contract.
- Error handling is machine-readable and remains backward-compatible for old persisted results.
- Duplicate request keys do not create duplicate tasks.
- Worker restart can recover an expired running task.
- Fake integration flow covers success, partial failure, captcha intervention, and cancellation without external services.
- Artifact metadata is verifiable without exposing filesystem paths.
- Security tests prove oversized/invalid requests and secret leakage are rejected.
- Full Python tests, fake smoke test, and frontend build pass before completion.
