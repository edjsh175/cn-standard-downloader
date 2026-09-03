# guobiao-crawler 架构审计与整改 PRD

版本：v1  
日期：2026-06-17  
审视角色：架构师 / 安全负责人 / 后端负责人 / 前端负责人 / DevOps / 开发 Agent 体验负责人  
审视范围：Python worker、爬虫核心、任务存储、HTTP API、Vue Web console、配置与部署、测试、文档、Agent 调用契约。

## 1. 背景

当前项目已经从本地 GUI 下载器演进为“可被 AI/Agent 调用的国标检索与下载执行引擎”。这是正确方向：项目有 HTTP worker、任务状态、artifact 输出、Web console、Docker 部署、契约测试和基础鉴权。

但当前架构仍保留大量单机脚本/GUI 时代的全局状态、同步阻塞、手写协议、长函数和副作用。这些问题在单人本地运行时可接受；如果目标是行业高标准的生产级 Agent 工具，需要把它升级为“契约清晰、可观测、可恢复、可扩展、可验证、可安全暴露”的服务。

## 2. 外部标准基准

本 PRD 对齐以下行业/官方基准：

- OWASP API Security Top 10 2023：鉴权、对象级授权、资源消耗、防止内部信息泄露、日志审计。
- OWASP REST Security Cheat Sheet：Content-Type 校验、输入验证、错误响应、TLS、日志与速率限制。
- OpenAPI Specification：API 契约、请求/响应 schema、错误模型和客户端生成。
- Selenium 官方文档：Selenium Manager、显式等待、减少硬编码 sleep。
- Docker 官方 build best practices 与 build secrets：镜像可复现、secret 不进镜像层、最小权限、供应链治理。
- Vue 官方性能建议：大型列表虚拟化、代码拆分、状态与组件职责清晰。
- Python Packaging User Guide：`pyproject.toml`、依赖元数据、工具配置集中化。

## 3. 当前系统全局评价

### 3.1 已经做得好的部分

- 有明确主入口：`run_worker.py` 启动 `app.worker_service.run_worker_server`。
- 有 Agent 契约：`app/agent_contract.py` 定义任务类型、终态、artifact 名称、推荐工作流和错误分类。
- API 默认需要 Bearer token；前端 token 放在 `sessionStorage`，不会被构建进静态产物。
- `TaskStore` 将任务状态与 item 状态持久化到 MySQL，支持任务结果查询。
- `PipelineRunner` 能把搜索、下载、artifact、任务状态串联成端到端流程。
- Docker 镜像使用非 root 用户；`docker-compose.yml` 有 healthcheck、resource limit 和 `no-new-privileges`。
- 后端已有 25 个 Python 单元测试；前端已有 Vitest 契约测试。

### 3.2 核心短板

- 架构边界不清：爬虫、配置、DB、浏览器、artifact、worker 状态强耦合。
- 缺少正式 API schema：前后端类型和 Agent 契约靠手写同步。
- 缺少生产级任务调度：当前是单进程内存队列，不支持重启恢复、租约、重试策略、并发隔离和背压。
- 配置是全局可变状态：`config.update_config()` 会影响已导入模块，天然不适合并发任务。
- 错误体系不足：错误主要靠字符串匹配与 broad `except`，无法稳定驱动 Agent 决策。
- 可靠性不足：大量 `time.sleep()`、浏览器全局状态和 monkey patch，导致 flaky 与不可预测。
- 安全边界不够：验证码服务使用明文 HTTP；Chrome 启动参数偏宽；API 缺少请求体大小限制、速率限制、统一错误遮蔽和审计日志。
- 供应链存在风险：`drivers/chromedriver.exe` 被 Git 跟踪；`npm audit` 报告 `xlsx` high vulnerabilities 且无修复版本；Vite/esbuild 链路有 moderate vulnerability。
- 前端职责过重：`web/src/App.vue` 聚合表单、轮询、文件解析、结果展示和下载逻辑，后续维护成本高。

## 4. 接口与功能逐项审视

### 4.1 Worker API

当前功能：

- `GET /api/health`
- `GET /api/contract`
- `GET /api/tasks`
- `POST /api/tasks`
- `GET /api/tasks/{task_id}`
- `GET /api/tasks/{task_id}/result`
- `GET /api/tasks/{task_id}/artifacts`
- `GET /api/tasks/{task_id}/artifacts/{name}`
- `GET /api/tasks/{task_id}/pdf/{filename}`
- `POST /api/tasks/{task_id}/cancel`

不足：

- API 没有 OpenAPI 文档，缺少请求/响应 schema、错误码定义、示例和兼容策略。
- `BaseHTTPRequestHandler` 手写路由可控但扩展成本高；路由、鉴权、序列化、错误处理全部混在一个类里。
- `_read_json()` 直接读取 `Content-Length`，缺少最大 body 限制、Content-Type 校验、JSON decode 分类和字段级错误定位。
- 500 错误会把 `str(exc)` 返回给调用方，存在内部信息泄露风险。
- Artifact 下载一次性读入内存，面对大 PDF/Excel 会造成内存尖峰。
- Auth 只有单 token，没有 token scope、过期、轮换、审计字段、调用方身份。
- 缺少 rate limit / concurrent request limit / queue depth limit 暴露。

PRD 要求：

- R-API-001：引入 OpenAPI 3.1 契约，覆盖所有 endpoint、请求体、响应体、错误体、artifact 类型。
- R-API-002：统一错误响应模型：`error.code`、`error.message`、`error.retryable`、`error.category`、`request_id`。
- R-API-003：新增请求体大小限制，默认 2 MB；直接 URL 批量提交行数默认上限 500，可配置。
- R-API-004：所有 API 响应带 `request_id`；日志可按 `request_id`、`task_id`、`item_id` 关联。
- R-API-005：文件下载改为 streaming response，避免一次性读入内存。
- R-API-006：保留现有 endpoint 兼容一版；新契约通过 `/api/v1/*` 固化。

验收标准：

- OpenAPI 文件可通过 schema lint。
- 前端 TypeScript 类型由 schema 生成或至少由 schema 校验。
- 所有 4xx/5xx 响应不泄露 traceback、DB host、文件绝对路径、token 或第三方账号。
- 超大 body、错误 Content-Type、非法 JSON、非法任务类型均有稳定错误码。

### 4.2 任务生命周期

当前状态：

- `queued`、`running`、`succeeded`、`failed`、`cancelled` 等状态已存在。
- 单进程 `queue.Queue` 驱动执行。
- MySQL 中持久化任务与 item。

不足：

- 队列只在内存，进程重启后 queued/running 任务不会自动恢复。
- 没有租约/心跳，worker 崩溃后任务可能永久卡在 `running`。
- cancel 是 best-effort，爬虫内长阻塞阶段不一定及时响应。
- 没有优先级、并发度、最大队列深度、任务超时、任务重试策略。
- 没有任务状态机约束，非法状态跳转无法被系统阻止。

PRD 要求：

- R-TASK-001：将任务调度状态机显式化，定义合法状态迁移。
- R-TASK-002：新增任务租约字段：`lease_owner`、`lease_until`、`heartbeat_at`、`attempt_count`。
- R-TASK-003：worker 启动时自动回收过期 `running` 任务，按策略重试或标记失败。
- R-TASK-004：每个任务支持 `timeout_seconds`、`max_attempts`、`priority`，默认配置在服务端控制。
- R-TASK-005：cancel 信号向 pipeline、searcher、crawler 分层传播，所有长循环每一步检查。
- R-TASK-006：暴露 queue metrics：queued/running/succeeded/failed/cancelled 数量、平均耗时、最近错误。

验收标准：

- kill worker 后重启，过期 running 任务能自动恢复或失败闭环。
- cancel 在搜索分页、下载等待、验证码阶段均能在可接受时间内生效。
- 并发度设置为 1 时行为与当前兼容；设置为 N 时任务之间不共享可变配置。

### 4.3 Agent 契约

当前优点：

- `app/agent_contract.py` 已给出 task types、terminal states、artifact names、recommended workflow。
- `build_agent_status()` 能把任务状态转换成 Agent 可读结果。

不足：

- 错误分类依赖字符串 substring，长期不稳定。
- 契约不是单一事实源，后端、前端、文档仍需人工同步。
- 缺少“Agent 应如何重试、何时请求人工介入、如何确认 artifact 完整性”的机器可读策略。
- 缺少可追踪的 version negotiation。

PRD 要求：

- R-AGENT-001：把 Agent contract 变成 schema-first：`contract_version`、`api_version`、`capabilities`、`limits`、`error_catalog`。
- R-AGENT-002：错误码由异常类型/业务分支产生，不再靠 message substring 二次推断。
- R-AGENT-003：新增 `next_actions` 稳定枚举，例如 `retry_task`、`retry_item`、`download_artifact`、`ask_human_for_captcha`、`inspect_partial_results`。
- R-AGENT-004：Artifact 增加校验信息：`size_bytes`、`sha256`、`content_type`、`created_at`。
- R-AGENT-005：提供 `docs/AI_WORKER_API.md` 自动生成或至少由契约测试校验不漂移。

验收标准：

- Agent 可以只读 `/api/contract` 就知道任务限制、错误码、artifact 名称和推荐流程。
- 任意失败任务都能给出稳定、可机器处理的 `error_code` 和 `retryable`。

### 4.4 配置系统

当前状态：

- `config.py` 支持 `.env`、`config_user.json`、环境变量 override。
- 可以通过 `STD_*` 环境变量配置数据库、token、下载目录、headless 等。

不足：

- 默认配置包含本地 DB root、默认 token 等不适合生产的 fallback。
- `config.update_config()` 改全局变量，并同步到已 import 模块。
- 不同任务的配置 override 会污染同一进程内其他任务。
- 缺少类型校验、必填校验、secret redaction、配置来源报告。

PRD 要求：

- R-CONFIG-001：引入不可变 `Settings` 对象，启动时加载全局配置，任务级配置作为显式参数传递。
- R-CONFIG-002：生产模式下强制要求 `STD_WORKER_TOKEN`、DB secret、captcha secret，禁止默认 token。
- R-CONFIG-003：配置校验失败时服务拒绝启动，错误明确但自动脱敏。
- R-CONFIG-004：移除跨模块 `_sync_dependent_modules()`，用 dependency injection 传入 crawler/searcher/store。
- R-CONFIG-005：提供 `/api/config/redacted` 或日志启动摘要，只显示脱敏后的关键配置。

验收标准：

- 并发任务不会互相修改 `DOWNLOAD_DIR`、`BASE_PDF_DIR`、`HEADLESS_BROWSER`。
- 日志和 API 永不输出明文 DB password、worker token、captcha password。

### 4.5 数据层与 MySQL

当前优点：

- 有 `crawl_tasks` 和 `crawl_task_items` 持久化。
- `validate_table_name()` 限制表名，降低 SQL 注入风险。

不足：

- schema 由应用启动时 `CREATE TABLE IF NOT EXISTS` 管理，没有 migration。
- 每次操作新建连接，无连接池、超时、重试和事务边界。
- item upsert 循环逐条执行，任务量上来后吞吐差。
- `UNIQUE KEY uniq_task_url (task_id, detail_url(255))` 有长 URL 前缀碰撞风险。
- 缺少 archive/retention 策略。
- JSON 存 `LONGTEXT`，没有 schema version 或 JSON column 策略。

PRD 要求：

- R-DB-001：引入 migration 工具或至少建立版本化 SQL 迁移目录。
- R-DB-002：连接层增加 pool、connect/read/write timeout、重试退避和健康检查。
- R-DB-003：item 唯一键改为 `task_id + detail_url_hash`，保留原始 URL。
- R-DB-004：批量 upsert 使用 `executemany` + 事务。
- R-DB-005：任务表和 item 表增加必要索引：`status`、`created_at`、`updated_at`、`task_id/status`。
- R-DB-006：增加数据保留策略：任务、日志、artifact、PDF 的保留天数可配置。

验收标准：

- 1000 item upsert 在可接受时间内完成，且失败可回滚。
- migration 可在空库和已有库上重复执行。
- 长 URL 不因 255 前缀相同导致误判重复。

### 4.6 搜索模块

当前文件：`search_module.py`

当前功能：

- 通过 Selenium 打开国标检索页。
- 支持关键字分页检索。
- 使用 Scrapling 解析结果，失败时 Selenium fallback。
- 过滤“国家标准”“现行”等条件。
- 生成 Excel 供下载流程使用。

不足：

- `Searcher.run()` 约 200 行，职责过多。
- 大量硬编码 `time.sleep()`，不是显式等待。
- 浏览器、解析、过滤、去重、Excel 输出耦合。
- 错误只在日志/字符串层传播，无法精确区分网络失败、页面结构变化、无结果、验证码、解析失败。
- 缺少解析器契约测试和网页样本 fixture。

PRD 要求：

- R-SEARCH-001：拆分为 `SearchClient`、`SearchParser`、`SearchResultFilter`、`SearchExportService`。
- R-SEARCH-002：所有页面等待改为 Selenium explicit wait 或可复用 wait helper。
- R-SEARCH-003：搜索结果内部统一结构化模型：`standard_no`、`standard_name`、`status`、`type`、`detail_url`、`source_keyword`。
- R-SEARCH-004：新增页面样本 fixture，覆盖 Scrapling 和 Selenium fallback。
- R-SEARCH-005：支持 search-only 直接返回结构化结果，不依赖 Excel 作为模块间传输格式。

验收标准：

- 页面结构轻微变化时测试能定位 parser 失败。
- 搜索模块可以在无真实浏览器的 parser 单测中快速验证。

### 4.7 下载与抓取模块

当前文件：`grab_module.py`

当前功能：

- 打开标准详情页。
- 解析标准编号、名称、状态等元数据。
- 处理预览窗口、下载候选、验证码识别、浏览器下载 fallback。
- PDF magic/content-type 基础校验。
- 保存 DB 记录。

不足：

- `BatchCrawler` 超过 1200 行，是全系统最大风险集中点。
- 构造器/`setup_env()` 包含建目录、连 DB、起浏览器等副作用。
- `save_db()` 既做字段映射、插入/更新策略、日志又做 DB 操作，并存在不可达旧代码。
- 验证码服务通过 `http://upload.chaojiying.net/...` 明文请求，且无 timeout。
- 下载策略混杂 session download、browser download、captcha flow、preview window。
- 对 Chrome 配置依赖强，且安全参数偏宽。
- `process_one()` 既是 orchestration 又做页面交互、文件、DB 和错误处理。

PRD 要求：

- R-CRAWL-001：拆分 `BatchCrawler` 为 `DetailPageClient`、`MetadataExtractor`、`PdfDownloadService`、`CaptchaSolver`、`PersistenceService`。
- R-CRAWL-002：验证码客户端必须支持 timeout、retry、HTTPS 优先、secret redaction；若第三方仅支持 HTTP，需在文档中标为高风险并支持关闭。
- R-CRAWL-003：下载流程输出结构化 `DownloadResult`：`status`、`pdf_path`、`failure_code`、`attempts`、`source_strategy`。
- R-CRAWL-004：移除 `save_db()` 中不可达代码，DB 写入从 crawler 中剥离。
- R-CRAWL-005：每个 item 独立失败不应污染浏览器全局状态；必要时支持浏览器重启策略。
- R-CRAWL-006：PDF 校验升级：magic、content-type、最小大小、可选 hash、可选页数/可打开校验。

验收标准：

- 单 item 下载失败可给出稳定原因，例如 `captcha_failed`、`pdf_not_found`、`network_timeout`、`parse_failed`。
- 验证码服务不可用时任务可以按策略失败/跳过/请求人工介入。
- `BatchCrawler` 主流程降到可测试 orchestration 层，核心解析和下载可独立单测。

### 4.8 Pipeline

当前文件：`app/pipeline.py`

当前功能：

- 从 task store 获取任务。
- 根据任务类型执行 search-only、keyword search、direct grab。
- 生成/汇总 artifact。
- 追踪 item 状态。

不足：

- `execute()` 约 200 行，承担过多职责。
- 使用 `working_directory()` 修改进程全局 CWD，不适合并发。
- 调用 `config.update_config()` 修改全局配置。
- monkey patch `crawler.save_db` 用于追踪 item 写入，脆弱且难测试。
- 搜索结果、下载结果、DB 状态之间缺少清晰事件模型。

PRD 要求：

- R-PIPE-001：Pipeline 改为显式上下文对象 `TaskContext`，包含 task、settings、artifact_paths、logger、cancel_token。
- R-PIPE-002：禁止修改全局 CWD；所有文件路径显式传递。
- R-PIPE-003：crawler/searcher 通过接口返回结构化结果，pipeline 不再 monkey patch。
- R-PIPE-004：拆分 search、prepare items、download、finalize 四个阶段，每阶段有输入/输出契约。
- R-PIPE-005：每个阶段记录耗时、item 数、错误分布。

验收标准：

- Pipeline 单测可以 mock searcher/crawler/store，不启动浏览器。
- 并发执行两个任务时 artifact 目录、配置、日志互不干扰。

### 4.9 Scrapling 解析层

当前文件：`app/scrapling_parser.py`

优点：

- 解析逻辑比其他模块更小、更集中。
- 有 `parse_search_results()`、`parse_detail_meta()` 等明确函数。

不足：

- adaptive storage 写 `.tmp/scrapling/elements_storage.db`，并发和环境隔离策略不清。
- 解析契约缺少 HTML fixture 覆盖。
- 页面字段和业务过滤条件分布在 parser/searcher 之间。

PRD 要求：

- R-PARSE-001：建立 `tests/fixtures/html/`，保存脱敏页面样本。
- R-PARSE-002：解析输出用 dataclass 或 pydantic-style typed model。
- R-PARSE-003：adaptive storage 路径按 worker/task 或环境隔离，或明确关闭策略。

验收标准：

- 不访问网络即可跑完 parser 测试。
- 页面变更导致的解析失败能被 CI 发现。

### 4.10 前端 Web Console

当前文件：`web/src/App.vue`、`web/src/api.ts`、`web/src/types.ts`、`web/src/styles.css`

优点：

- token 不构建进静态产物。
- `withAuthHeaders()` 已避免 token 发往外部 URL。
- 支持 search-only、keyword search、direct grab、Excel 导入、artifact 下载。
- 有 Vitest 覆盖 API header、URL extraction、status helpers。

不足：

- `App.vue` 约 800 行，职责过重。
- 前端类型由手写维护，和后端契约可能漂移。
- 轮询没有 AbortController，切换任务时可能出现旧请求覆盖新状态。
- Excel 导入缺少文件大小、行数、列名、URL 类型和重复数量限制。
- `extractDetailUrls()` 只匹配 `/gb/search/gbDetailed`，后端支持范围更宽。
- 大结果表没有分页/虚拟列表。
- `styles.css` 存在重复规则，视觉上偏 landing/card-heavy，不够像高频操作台。
- 依赖 `xlsx` 有 high vulnerabilities 且无官方修复版本。

PRD 要求：

- R-WEB-001：拆分组件：`TaskForm`、`TaskStatusPanel`、`TaskResultTable`、`ArtifactDownloads`、`RecentTasks`、`TokenSettings`。
- R-WEB-002：抽出 composables：`useTaskPolling`、`useTaskSubmission`、`useExcelImport`、`useArtifacts`。
- R-WEB-003：轮询使用 AbortController，任务切换时取消旧请求。
- R-WEB-004：前端类型由 OpenAPI 生成，或引入 runtime validation。
- R-WEB-005：Excel/URL 导入增加大小、行数、重复、非法 URL 报告。
- R-WEB-006：大表增加分页或虚拟列表。
- R-WEB-007：替换或隔离 `xlsx`：优先服务端解析或选择维护状态更好的库；短期把导入文件大小限制降到保守值。
- R-WEB-008：UI 调整为内部工具风格：信息密度更高、圆角更克制、减少装饰性渐变、强化扫描和对比。

验收标准：

- 切换任务时不会出现旧任务状态覆盖当前任务。
- 1000 条结果展示不卡顿。
- 前端构建通过 typecheck；契约字段变更时类型生成或测试会失败。

### 4.11 GUI Legacy

当前文件：`gui_main.py`

不足：

- 单文件近 1700 行，保留大量 GUI、本地配置、爬虫控制逻辑。
- 与 worker 共享全局配置和模块状态。
- 行业高标准下，GUI 不应继续承担核心业务逻辑。

PRD 要求：

- R-GUI-001：明确 GUI 状态：deprecated / maintenance / removed。
- R-GUI-002：如果保留 GUI，只作为 worker API client，不直接调用 crawler 内部。
- R-GUI-003：核心能力只能存在于 service/domain 层，GUI 和 Web 都调用同一契约。

验收标准：

- GUI 删除或停用不影响 worker、API、测试和 Docker 部署。

### 4.12 浏览器与 Selenium

当前优点：

- Docker 安装 Chromium/chromedriver。
- 本地可用 repo driver、cache driver 或 webdriver_manager fallback。

不足：

- Git 跟踪 `drivers/chromedriver.exe`，供应链和平台兼容风险高。
- Selenium 4 已有 Selenium Manager，当前 driver 管理路径复杂。
- Chrome 参数包含 `--ignore-certificate-errors`、`--allow-running-insecure-content`、`--disable-web-security`、`--no-sandbox`、`--remote-debugging-port=9222` 等，需要按环境约束。
- 大量硬编码 sleep。

PRD 要求：

- R-BROWSER-001：删除 Git 跟踪的 driver 二进制，改为 Docker/system/Selenium Manager 管理。
- R-BROWSER-002：建立 `BrowserFactory`，统一设置、日志、下载目录、headless、proxy、timeouts。
- R-BROWSER-003：Chrome 高风险参数按环境开关；生产默认关闭远程调试端口。
- R-BROWSER-004：所有等待封装为显式等待 helper，减少固定 sleep。

验收标准：

- 本地、Docker、CI 三种环境 driver 策略清晰。
- 生产模式不会暴露 remote debugging port。

### 4.13 安全

主要风险：

- 验证码平台请求明文 HTTP。
- 默认配置和示例容易被误用为生产配置。
- API 单 token 鉴权过于粗粒度。
- 缺少 rate limit、body limit、审计日志、请求 ID。
- 500 错误可能泄露内部细节。
- `xlsx` 高危漏洞会被用户上传文件触发。
- Chrome 安全参数偏宽。
- Artifacts/PDF 路径和下载权限依赖 task ID，缺少更细粒度授权模型。

PRD 要求：

- R-SEC-001：安全基线文档：部署在内网/公网的前置条件、TLS、反向代理、IP allowlist、token rotation。
- R-SEC-002：请求限制：body size、rate limit、queue depth、max items、max artifact size。
- R-SEC-003：统一审计日志：who、when、action、task_id、status、request_id、client_ip。
- R-SEC-004：secret 管理：`.env` 仅本地；生产使用 Docker secrets/平台 secrets。
- R-SEC-005：依赖安全策略：npm audit/pip audit/镜像扫描纳入 CI。
- R-SEC-006：前端文件导入 sandbox：限制大小与行数；`xlsx` 替换前标为高风险。

验收标准：

- 安全测试覆盖未鉴权访问、错误 token、非法 JSON、超大请求、路径穿越、artifact 越权。
- CI 至少跑 npm audit 或有风险豁免文件。

### 4.14 可观测性

当前不足：

- 主要依赖文本日志。
- 缺少结构化日志、request_id、task_id 贯穿、指标和 tracing。
- Agent 无法快速判断是站点异常、验证码异常、DB 异常还是代码异常。

PRD 要求：

- R-OBS-001：结构化 JSON log，可配置 text/json。
- R-OBS-002：全链路字段：`request_id`、`task_id`、`item_id`、`phase`、`duration_ms`、`error_code`。
- R-OBS-003：新增 `/api/metrics` 或 Prometheus endpoint，至少包含任务计数、耗时、队列深度、失败原因分布。
- R-OBS-004：每个 task 生成简要 run report artifact。

验收标准：

- 单个失败 item 可以从 API 响应追到日志，再追到 artifact。
- 运维能看到最近 24 小时任务成功率和主要失败原因。

### 4.15 测试与质量门禁

当前结果：

- `python -m unittest discover -s tests -v`：25 tests passed。
- `npm test`：4 tests passed。
- `npm run typecheck`：passed。
- `npm run build`：passed。
- `npm audit --audit-level=moderate`：failed，包含 `xlsx` high vulnerabilities 和 Vite/esbuild moderate vulnerability。
- `python -m pip check`：passed。
- `python -m pip_audit`：不可用，当前环境未安装。

不足：

- 没有 CI 配置。
- Python 缺少 lint/typecheck/format 门禁。
- 浏览器 E2E 和 contract tests 覆盖不足。
- 没有 parser fixture、download fixture、DB migration tests。
- 没有性能测试和长任务恢复测试。

PRD 要求：

- R-QA-001：新增 CI：Python tests、frontend tests、typecheck、build、npm audit、pip audit/依赖扫描。
- R-QA-002：新增 lint/format：Ruff 或等价工具；前端 ESLint/Prettier 或等价工具。
- R-QA-003：新增 contract tests：OpenAPI schema 与后端响应一致。
- R-QA-004：新增 integration tests：task submit -> running -> result，使用 fake searcher/crawler。
- R-QA-005：新增 resilience tests：worker crash/restart、cancel、timeout、DB transient failure。

验收标准：

- PR 必须通过测试和 typecheck。
- 安全 audit 失败时要么修复，要么有带过期时间的风险豁免。

### 4.16 Docker 与部署

优点：

- 多阶段构建。
- 非 root 用户。
- healthcheck。
- compose 有资源限制。

不足：

- base image 未按 digest pin。
- Python 依赖没有 hash lock。
- npm 依赖有 audit 风险。
- 没有 SBOM、镜像扫描、签名。
- secret 通过 env 注入，生产环境不够理想。
- 没有标准化 release/version 信息。

PRD 要求：

- R-DEPLOY-001：镜像加入版本标签、git sha、build time labels。
- R-DEPLOY-002：生产镜像 base image digest pin 或建立定期 rebuild 策略。
- R-DEPLOY-003：引入 SBOM 和镜像漏洞扫描。
- R-DEPLOY-004：secret 使用 Docker secrets 或部署平台 secret。
- R-DEPLOY-005：运行时最小权限：read-only root fs 可选、只挂载 artifact/tmp 必需目录。
- R-DEPLOY-006：补充备份、恢复、升级、回滚、日志轮转 runbook。

验收标准：

- 任意部署版本可追溯到 git commit。
- secret 不出现在镜像层、前端 bundle、日志和 artifact。

### 4.17 文档

当前文档：

- `README.md`
- `docs/AI_WORKER_API.md`
- `DEPLOY_DOCKER.md`
- `QUICK_START_DOCKER.md`

不足：

- 文档与代码契约可能漂移。
- 缺少架构图、状态机图、错误码目录、数据字典、运维 runbook。
- 缺少 Agent 最佳实践：如何提交、轮询、取消、重试、下载 artifact。

PRD 要求：

- R-DOC-001：新增架构总览：组件、数据流、任务状态机、artifact 生命周期。
- R-DOC-002：API 文档由 OpenAPI 生成或测试校验。
- R-DOC-003：新增错误码目录。
- R-DOC-004：新增 Agent Playbook：最佳调用流程、重试策略、失败处理、人类介入点。
- R-DOC-005：新增操作手册：部署、备份、恢复、升级、排障。

验收标准：

- 新开发者可在 30 分钟内本地启动 worker、提交测试任务、理解主要目录。
- Agent 可按文档完成完整任务闭环。

## 5. 开发 Agent 视角还缺什么

为了让该项目成为“优秀开发 Agent 能高质量协作”的代码库，还缺少以下能力：

1. 单一事实源：OpenAPI/schema、错误码、任务状态、artifact 定义要从同一个地方生成。
2. 可快速反馈：无浏览器 parser 单测、fake crawler integration test、contract test。
3. 可安全试错：本地 fake mode/mock mode，不访问真实国标站点、不调用验证码、不写生产 DB。
4. 可恢复任务：Agent 不怕 worker 重启，能继续查任务状态。
5. 可解释失败：每个失败必须有稳定错误码、retryable、human_action_required。
6. 可观测链路：request_id/task_id/item_id 打通日志、API、artifact。
7. 可控副作用：无全局 mutable config、无全局 CWD 修改、无 monkey patch。
8. 可拆分 issue：模块边界明确，Agent 能一次改一个模块并有测试保护。
9. 可审计安全：secret redaction、依赖审计、镜像扫描、风险豁免文件。
10. 可自动生成文档：API、类型、Agent playbook 尽量由契约生成或测试保护。

## 6. 优先级路线图

### P0：安全与契约止血

- 建立统一错误响应和错误码。
- 增加 body size limit、Content-Type 校验、500 错误遮蔽。
- 前端导入文件大小/行数限制。
- 标记并缓解 `xlsx` 漏洞风险。
- 禁止生产默认 token。
- 去除或环境化高风险 Chrome 参数，生产默认关闭 remote debugging port。

### P1：可恢复任务与 schema-first

- OpenAPI 3.1 契约。
- 任务状态机、租约、心跳、重启恢复。
- Artifact metadata：size/hash/content_type。
- 前后端类型生成或 contract test。
- request_id/task_id 结构化日志。

### P2：核心模块解耦

- Searcher 拆分 parser/client/filter/export。
- BatchCrawler 拆分 metadata/download/captcha/persistence。
- Pipeline 使用 TaskContext，不再改 CWD、不再改全局配置、不再 monkey patch。
- DB migration、连接池、批量 upsert、URL hash 唯一键。

### P3：生产化与规模化

- CI/CD、lint/typecheck/audit/镜像扫描/SBOM。
- metrics endpoint 与运行报告。
- 前端组件化、虚拟列表、内部工具 UI 改版。
- GUI legacy 去核心化或退役。
- 完整运维 runbook。

## 7. 推荐 PR 拆分

1. PR-001：API 安全基线：body limit、Content-Type、统一错误、request_id。
2. PR-002：OpenAPI 契约与前后端类型校验。
3. PR-003：任务状态机、租约、重启恢复。
4. PR-004：配置系统改为不可变 Settings。
5. PR-005：Pipeline TaskContext 化，去 CWD/global config/monkey patch。
6. PR-006：DB migration、连接池、批量 upsert、URL hash。
7. PR-007：Searcher 拆分与 parser fixture 测试。
8. PR-008：BatchCrawler 拆分、验证码客户端安全化、下载结果结构化。
9. PR-009：前端组件化、AbortController、导入限制、大表分页/虚拟列表。
10. PR-010：CI、安全审计、SBOM、镜像扫描、release metadata。
11. PR-011：Agent Playbook、错误码目录、运维 runbook。
12. PR-012：GUI legacy 去核心化或退役。

## 8. 成功指标

- 任务可靠性：worker crash 后任务能恢复或稳定失败闭环。
- API 稳定性：所有错误有稳定 error code，Agent 无需解析自然语言。
- 安全性：无默认生产 secret；依赖 audit 风险有修复或正式豁免。
- 可维护性：最大核心函数降到 80 行以内，最大核心类职责单一。
- 可测试性：无需真实浏览器即可跑 parser/domain tests；fake crawler 可跑 worker integration tests。
- 可观测性：每个任务可追踪 phase duration、失败原因、artifact hash。
- 前端体验：1000 条结果不卡顿；任务切换无状态串扰。
- 交付能力：每个 PR 有独立测试与回滚边界。

## 9. 当前验证证据

- Python unit tests：通过，25 tests。
- Frontend unit tests：通过，4 tests。
- Frontend typecheck：通过。
- Frontend build：通过。
- Python dependency consistency：`pip check` 通过。
- npm audit：未通过，存在 `xlsx` high vulnerabilities 与 Vite/esbuild moderate vulnerability。
- pip audit：本地工具未安装，尚未完成。

## 10. 结论

该项目已经具备“Agent 可调用爬虫执行器”的雏形，但还不是生产级 Agent 平台。最高优先级不是继续加新抓取功能，而是先把契约、安全、任务恢复、全局状态隔离和错误模型补齐。完成 P0/P1 后，Agent 才能稳定调用；完成 P2 后，开发者和 Agent 才能安全演进；完成 P3 后，才接近可长期运维的生产服务。

