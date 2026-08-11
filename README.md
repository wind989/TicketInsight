# TicketInsight

## SSE progress (status only)

中文 API 约束说明见 `docs/api.md`。

Start one independent analysis with `POST /api/v1/analysis-runs/async`. It returns `202`, a run ID, and an
`events_url`; subscribe with `GET /api/v1/analysis-runs/{run_id}/events` using `text/event-stream`.
Each `progress` event contains only `run_id`, stage, status, an approved short summary, and a timestamp. The
in-process tail is capped at 32 events per run. It is not token streaming and never carries raw SQL, ticket or
knowledge text, model output, credentials, connection strings, or a final conclusion.

An unknown run ID returns `404`. This local prototype has no authentication layer; when one is introduced, an
unowned run must receive the same `404` response. Disconnecting a client only closes its subscription: the
background analysis owns a separate database session and still persists its terminal state. Completed, limited,
and failed runs emit one terminal status event. After a process restart removes the bounded event tail, the stream
may emit only a durable, safe terminal status.

SSE is not a report API. Read the final persisted, auditable report through the existing
`GET /api/v1/analysis-runs/{run_id}` endpoint after its terminal event.

> 2026-08-10 本机模型验证：已显式下载 `BAAI/bge-small-zh-v1.5` 到本项目忽略的 `.model-cache/`，并完成离线加载与 512 维向量编码验证。生产运行时仍只允许本地加载，不会隐式下载模型。

> 2026-08-10 本机服务验证：Docker MySQL 8.4 与 Qdrant 已使用专用卷启动；迁移至 `20260809_0002` 后导入合成数据，并完成真实 BGE+Qdrant 检索及只读 MySQL 查询验收。MySQL、Qdrant 和应用 HTTP 端口均仅绑定 `127.0.0.1`；应用入口为 `http://127.0.0.1:8010`。

> 2026-08-10 检索基线：在 15 条固定合成运营题中，14 条具有可评分的证据类型标签；真实 BGE+Qdrant 的 Top-1 为 10/14（71.43%），Recall@3 为 14/14（100%）。该指标仅代表当前小型合成语料，不外推真实客服数据或完整 Agent 质量。

> 2026-08-10 真实 Agent 验收：已使用本机 DeepSeek 配置对合成支付问题运行一次固定 LangGraph 图。两次模型 SQL 都被 AST 在执行前拒绝，随后只基于检索证据生成带限制说明的结论，并在一次结论修订后通过复核。运行标为 `limited`，表示安全受限完成；该次运行不证明模型 SQL 规划质量已达标。

> 2026-08-10 完整 Agent 基线：修复有界修订计数后，以本机 DeepSeek 配置重跑 15 条固定合成题。13 条 `completed`、2 条 `limited`、0 条 `failed`；14/14 可评分题的证据类型命中，10/12 所需 SQL 表匹配，13/15 完成受限只读查询。该报告不保存题目、SQL、行数据、证据正文或模型输出，且不自动评估结论语义正确性；它是本机合成工作流基线，不外推真实客服或生产质量。

客服工单智能分析与运营决策平台。

TicketInsight 面向客服主管、售后运营和产品运营，目标是将“为什么某类投诉增加”“哪些高优先级工单超 SLA”“哪个模块问题最集中”等问题，拆为可追溯的检索、只读数据查询、归因和复核流程。

## 当前状态

项目刚从原 API 测试方向切换至 TicketInsight。当前已有可隔离验证的实现，但尚未达到真实环境的完整验收：

| 阶段 | 已实现并验证 | 尚未完成/验证 |
| --- | --- | --- |
| P0 | 领域模型、两份 Alembic 迁移、固定合成数据、CRUD/筛选 API、PII 基础拒绝、真实三账号 MySQL 迁移与 E2E | 真实客服数据接入不在范围内 |
| P1 | 统一证据记录、本地 BGE 512 维编码、真实 Qdrant 合成检索，固定检索基线（Top-1 10/14、Recall@3 14/14） | 真实客服语料评测不在范围内 |
| P2 | sqlglot AST 白名单、行数限制、SQLite 隔离执行、真实 MySQL 只读有界查询与审计；SLA 专用 `TIMESTAMPDIFF` 最小放行 | 更广泛性能压测未执行 |
| P3 | LangGraph 固定图、SQL/结论各一次修订上限、运行记录与持久化、真实 DeepSeek 合成 E2E | 不增加写操作或开放式工具调用 |
| P4 | 15 条固定运营题、19 条 SQL 安全评测、完整真实 Agent 合成基线（13 completed、2 limited、0 failed）、数值化人工语义评审框架 | 结论语义正确性尚无人工标注评分 |
| P5 | 脱敏 JSON 日志、离线演示、Docker Compose、MySQL/Qdrant/App 本机容器与 SSE 验证、GitHub Actions 远程 CI | 生产部署验收未执行 |

## 目标架构

运营问题 → 检索 Agent → SQL 规划 Agent → 代码安全闸门 → 只读 MySQL → 归因/建议 Agent → Reviewer → 带证据的报告。

完整设计见：

- docs/requirements.md
- docs/architecture.md
- docs/diagrams.md（系统流程图与业务流程图）
- ../项目设计/TicketInsight/设计蓝图.md

## 当前骨架的本地启动

Docker Compose 默认使用宿主机 `8010`（容器内仍为 `8000`），避免与其他本机服务冲突。

1. 创建并激活 Python 虚拟环境。
2. 执行 pip install -e ".[dev]"。
3. 执行 uvicorn app.main:app --reload。
4. 访问 http://127.0.0.1:8000/health 或 http://127.0.0.1:8000/docs。

## P0 本地数据库与合成数据

1. 将 `.env.example` 复制为本机忽略的 `.env`，配置三个本项目专用连接：`TICKETINSIGHT_DATABASE_URL` 仅供 FastAPI CRUD（`ticketinsight_app`，无 DDL）、`TICKETINSIGHT_READONLY_DATABASE_URL` 仅供 P2 分析执行器（`ticketinsight_readonly`，仅 SELECT）与 `TICKETINSIGHT_MIGRATION_DATABASE_URL` 仅供本机 Alembic 命令（`ticketinsight_migrator`）。不要提交 `.env` 或任何密码。
2. 仅在本机维护环节执行 `./.venv/Scripts/python.exe scripts/migrate.py upgrade`。迁移账号不可配置给 FastAPI 运行时或任何 Agent。
3. 执行 `./.venv/Scripts/python.exe scripts/seed_synthetic.py`，导入固定的匿名客户、工单、SLA 与 SOP/FAQ 示例。
4. 使用 Swagger 的 `/api/v1/*` 资源接口管理合成数据；`POST /api/v1/demo/seed` 重复调用是幂等的。

P0 会拒绝包含明显邮箱或中国大陆手机号的工单/知识文本，并且只使用 `anon-` 前缀的客户匿名标识。这不是完整 PII 检测器，不应用于导入真实客服数据。

## 安全边界

- FastAPI 运行时只使用 `ticketinsight_app` CRUD 连接；迁移 URL 只由 Alembic 环境读取，绝不传给 FastAPI 或 Agent。
- 分析执行器只读取 `ticketinsight_readonly` URL。它先用 sqlglot 校验单条 SELECT、表/字段/函数白名单、禁止跨库/子查询/多语句/文本正文列，再执行行数和超时限制。
- 唯一额外标量函数是 SLA 时长分析专用的 `TIMESTAMPDIFF`：仅 `MINUTE`、`HOUR`、`DAY` 与带表限定的 `tickets` 时间列或固定受控时间字面量；嵌套函数、跨表/跨库参数和正文列在连接前拒绝。
- 工单与知识文本被当作不可信证据；模型只有结构化规划、归因和复核职责，没有数据库、Shell、HTTP 或写操作工具。
- 日志不写请求体、查询参数、授权头、密钥、完整问题、完整工单文本、邮箱或手机号。

## 评测与报告

固定题集位于 `evaluation_sets/synthetic_operations_v1.json`。固定 SQL 安全用例可以离线运行：

```powershell
./.venv/Scripts/python.exe scripts/evaluate_sql_safety.py
```

报告写入 `reports/sql_safety_evaluation.json`。它只能证明该版本 AST 闸门在固定候选 SQL 上的行为，不能外推为真实模型、真实客户数据或生产安全性。

还可以运行不依赖外部服务的演示：

```powershell
./.venv/Scripts/python.exe scripts/demo_offline.py
```

它写入 `reports/offline_demo.json`，其中会明确标注 `offline_fake`。该演示使用内存 SQLite、内存 Qdrant、确定性测试嵌入器和 Fake LLM；它展示流程形状与审计格式，不是任何真实环境的性能或质量证据。

真实模型的固定集报告不自动判断结论语义正确性。后续人工评审只能复制 `evaluation_sets/semantic_review_template_v1.json` 到本机忽略的 `evaluation_reviews/semantic_review_v1.local.json`，并针对每个固定 ID 填写三项 1–5 的数值：结论直接性、证据支撑度、限制说明诚实度。模板和汇总器不接受问题、SQL、模型输出或自由文本备注；完整填完 15 项后才可运行：

```powershell
./.venv/Scripts/python.exe scripts/summarize_semantic_review.py --input evaluation_reviews/semantic_review_v1.local.json
```

它只生成数值聚合报告。当前尚未进行人工评分，因此不能把这项框架或 15 题运行指标写成语义质量结论。

## Docker 与 CI

`docker-compose.yml` 将业务运行、只读分析和迁移账号分离；迁移容器只在 `maintenance` profile 下运行，应用容器不接收迁移 URL。MySQL、Qdrant 和应用 HTTP 端口均只绑定 `127.0.0.1`。本机已用最新镜像启动 MySQL、Qdrant 与应用容器，验证 `/health`、`/ready` 与完成运行的 SSE 安全终态。`requirements.lock` 固定已验证的 Python 3.11 依赖，Docker 基础镜像固定到已验证摘要；GitHub Actions 使用相同约束在干净 Ubuntu 环境完成编译、测试和依赖检查。

## 当前骨架的测试

执行 `./.venv/Scripts/python.exe -m pytest -q`。

当前本机证据：51 项 pytest 通过；`compileall`、`pip check` 与 Docker Compose 配置检查通过；固定 SQL 安全评测为 19/19。真实 MySQL、Qdrant、本地 BGE、15 题真实模型固定集和最新 Docker SSE 容器均已验证；GitHub Actions 已在干净 Ubuntu 环境成功运行。生产部署仍未验证。固定评测报告只含脱敏聚合事实，不能替代真实客户场景或人工语义验收。

## 数据与安全承诺

- 初期只使用合成或已脱敏的服务数据；
- 后续数据库分析只允许经 sqlglot 校验的单条只读 SQL；
- 不记录密钥、授权头、电话、邮箱、完整姓名或完整工单正文；
- 不自动回复客户、变更工单或执行外部写操作。
