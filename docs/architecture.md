# TicketInsight 架构说明

## 原则

模型负责建议，代码负责约束。任何可能扩大读取范围、执行 SQL 或生成关键结论的动作，都需要确定性代码和审计记录。

目标组件：FastAPI 和 Swagger 提供入口；后续 LangGraph 编排受限检索、SQL 规划、归因和复核；sqlglot、白名单、行数与超时限制构成 SQL 安全闸门；MySQL 专用只读账号提供统计数据；运行、证据、SQL 审计和反馈持久化。

### SLA 时长计算的最小例外

SQL 安全闸门只额外放行 MySQL 的 `TIMESTAMPDIFF`，且只服务于工单 SLA 时长或超时分析。时间单位只能是 `MINUTE`、`HOUR` 或 `DAY`；后两个参数只能是带表限定的 `tickets.created_at`、`tickets.first_response_at`、`tickets.resolved_at`，或固定格式的受控时间字面量。函数嵌套、子查询、跨库、跨表时间比较、正文列及任意其他表达式均会在连接只读数据库前拒绝。

这不是通用函数白名单：仍只允许单条 `SELECT`、已授权表字段、受限 `LIMIT`、执行超时和专用只读账号。审计与报告保留的是脱敏结构化结果，不保留原始 SQL、问题、行数据或模型输出。

## 当前实现边界

当前已在本机合成/脱敏环境完成 FastAPI、三类 MySQL 账号与 Alembic、Qdrant 本地 BGE 检索、固定 LangGraph、SQL 审计/持久化、SSE 状态进度、固定题集评测及 Docker Compose 验证。模型只能产生受审计的规划、归因建议和表达；检索与数据库读取范围由确定性代码决定。

已验证的真实模型固定集只代表该合成环境：15 题中 13 条完成、2 条受限、没有失败，且未自动评判模型结论的语义正确性。GitHub Actions 已在干净 Ubuntu 环境验证；生产部署、真实客服数据导入、自动客户触达、写操作 Agent 均不在当前验收范围。

人工语义验收使用 `evaluation_sets/semantic_review_template_v1.json`：它只接受固定题目 ID 与三项 1–5 数值评分，拒绝自由文本、题目、SQL 和模型输出。汇总器只在 15 项均完成时生成匿名数值聚合；在没有真实人工完成该表之前，项目不声明任何语义质量分数。

## 开发顺序

1. P0：领域模型、MySQL、Alembic、脱敏模拟数据、CRUD、测试。
2. P1：Embedding、Qdrant、证据检索。
3. P2：受控 SQL 与审计。
4. P3：LangGraph 多 Agent 和有限反思。
5. P4/P5：评测、日志、演示、Docker 与 CI。
