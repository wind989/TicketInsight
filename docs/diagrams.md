# TicketInsight 系统与业务流程图

本文档描述当前已实现的本地合成/脱敏环境。图中的 LLM 只负责理解、SQL 规划、归因和复核；它没有数据库、Shell、HTTP 或写操作工具。所有真实数据读取都必须经过确定性代码的安全校验，并使用专用只读账号。

## 系统流程图

```mermaid
flowchart TB
    operator["客服主管 / 售后运营 / 产品运营"]
    swagger["Swagger / FastAPI API\n资源管理、分析运行、报告查询"]
    sse_client["SSE 订阅者\n仅接收安全进度状态"]

    operator --> swagger
    operator --> sse_client

    subgraph app["TicketInsight FastAPI 应用"]
        direction TB
        input_guard["输入边界\n拒绝空值与明显 PII\n只接收合成/脱敏文本"]
        resource_api["领域资源 API\n客户、工单、SLA、模块、事件、服务知识"]
        analysis_api["分析 API\n同步运行 / 异步启动\n报告与反馈查询"]
        run_store["运行服务\n创建 run、持久化终态\n保存脱敏报告要素"]
        progress["进度注册表\n每个 run 最多 32 条\n只保留状态安全摘要"]
        sse["SSE 流\ntext/event-stream\n心跳、断开不取消任务"]
        logs["脱敏 JSON 日志\n不记录密钥、授权头、正文、原始模型输出"]

        input_guard --> resource_api
        input_guard --> analysis_api
        analysis_api --> run_store
        run_store --> progress
        progress --> sse
        run_store --> logs
    end

    swagger --> input_guard
    sse_client --> sse

    subgraph graph["固定 LangGraph 分析图（无开放式 ReAct 循环）"]
        direction TB
        retrieve["1. 证据检索节点"]
        planner["2. SQL 规划节点\nLLM 只输出候选计划"]
        gate["3. 确定性 SQL 安全闸门\nsqlglot AST、单条 SELECT\n表/列白名单、LIMIT、超时\nTIMESTAMPDIFF 仅 SLA 安全子集"]
        executor["4. 有界只读执行器\n行数限制 + 查询超时"]
        advisor["5. 归因建议节点\nLLM 仅基于受限输入起草"]
        reviewer["6. Reviewer / Reflection\n批准、一次 SQL 修订或一次结论修订"]
        terminal["终态\ncompleted / limited / failed"]

        retrieve --> planner --> gate
        gate -->|"通过"| executor --> advisor --> reviewer
        gate -->|"拒绝且未超过 1 次"| planner
        gate -->|"拒绝且已达上限"| advisor
        reviewer -->|"修订 SQL 且未超过 1 次"| planner
        reviewer -->|"修订结论且未超过 1 次"| advisor
        reviewer -->|"批准或达到上限"| terminal
    end

    run_store --> retrieve
    terminal --> run_store
    progress -. "只含阶段、状态、受控摘要、时间戳" .-> sse

    subgraph ai["本地检索与受控模型能力"]
        direction LR
        bge["本地中文 BGE\nBAAI/bge-small-zh-v1.5"]
        qdrant["Qdrant\n工单 / SOP / FAQ / 已知问题证据向量"]
        llm["DeepSeek LLM\n规划、归因、复核\n不持有数据库工具"]
        bge <--> qdrant
    end

    retrieve --> bge
    planner --> llm
    advisor --> llm
    reviewer --> llm

    subgraph mysql["MySQL：按职责隔离账号"]
        direction TB
        domain[("业务领域数据\n客户、工单、SLA、模块、事件、服务知识")]
        audit[("审计与分析记录\nrun、证据引用、SQL 审计、节点轨迹、匿名反馈")]
        app_user["ticketinsight_app\n业务 CRUD 与报告持久化\n无 DDL"]
        read_user["ticketinsight_readonly\n仅 SELECT\n仅供有界分析执行器"]
        migrator["ticketinsight_migrator\n仅 Alembic 维护时使用\n运行时与 Agent 不可用"]
        app_user --> domain
        app_user --> audit
        read_user --> domain
        migrator --> domain
        migrator --> audit
    end

    resource_api --> app_user
    run_store --> app_user
    executor --> read_user
    gate -. "拒绝后绝不连接只读库" .-> executor

    subgraph delivery["工程化与验证"]
        compose["Docker Compose\nApp + MySQL + Qdrant"]
        migration["Alembic 迁移\nmaintenance profile"]
        tests["pytest、SQL 安全评测\n离线演示、固定题集"]
        ci["GitHub Actions\n锁定依赖、编译、测试、pip check"]
        compose --> migration
        tests --> ci
    end

    migration --> migrator
    compose --> app
    compose --> mysql
    compose --> ai

    classDef guard fill:#fff1f2,stroke:#be123c,color:#4c0519;
    classDef data fill:#ecfeff,stroke:#0e7490,color:#083344;
    classDef agent fill:#f5f3ff,stroke:#6d28d9,color:#2e1065;
    classDef output fill:#ecfdf5,stroke:#047857,color:#064e3b;
    class input_guard,gate guard;
    class domain,audit,qdrant data;
    class retrieve,planner,advisor,reviewer,llm agent;
    class terminal,sse,logs output;
```

## 业务流程图

```mermaid
flowchart TD
    start(["运营人员提出分析问题"])
    scope["明确分析范围\n时间、工单类别、产品模块、优先级、SLA"]
    pii{"问题是否为空或包含明显 PII？"}
    reject_input["拒绝请求\n不创建分析运行"]
    create_run["创建 analysis run\n状态 = running\n记录脱敏问题与图版本"]

    subgraph evidence["A. 建立可追溯证据"]
        direction TB
        synthetic["仅使用合成/脱敏的\n客户、工单、事件、SLA、模块、SOP/FAQ"]
        index["本地 BGE 编码\n写入 Qdrant 统一证据索引"]
        retrieve_business["按问题检索 Top-K 证据\n返回来源类型、业务 ID、标题、脱敏摘录、分数"]
        synthetic --> index --> retrieve_business
    end

    subgraph query["B. 受控统计查询"]
        direction TB
        plan["LLM 提出 SQL 候选与理由\n不直接执行"]
        validate{"确定性安全校验是否通过？\n单条 SELECT、白名单表/列、\n无跨库/子查询/DML/DDL、\nLIMIT、SLA 时间函数安全子集"}
        audit_reject["记录脱敏拒绝审计\n不连接数据库"]
        repair_sql{"SQL 修订是否已用过？"}
        safe_query["只读账号执行\n超时、行数限制\n返回聚合结果与审计摘要"]
        limited_data["无统计结果继续分析\n结论必须说明限制"]
        plan --> validate
        validate -->|"否"| audit_reject --> repair_sql
        repair_sql -->|"否，允许一次"| plan
        repair_sql -->|"是"| limited_data
        validate -->|"是"| safe_query
    end

    subgraph conclusion["C. 归因、复核与交付"]
        direction TB
        draft["归因建议 Agent\n只使用检索证据、受控查询结果与拒绝原因\n生成结论 + 限制说明"]
        review{"Reviewer 是否批准？"}
        revise_sql{"要求修订 SQL 且未用过？"}
        revise_conclusion{"要求修订结论且未用过？"}
        report["持久化最终报告\n状态、结论、限制、证据引用、\nSQL 审计、节点耗时"]
        final_state{"是否有受控查询结果？"}
        completed["completed\n结论有证据与只读统计支撑"]
        limited["limited\n流程安全完成但统计受限/不可用"]
        draft --> review
        review -->|"批准或达到修订上限"| report
        review -->|"需要调整"| revise_sql
        revise_sql -->|"是"| plan
        revise_sql -->|"否"| revise_conclusion
        revise_conclusion -->|"是"| draft
        revise_conclusion -->|"否"| report
        report --> final_state
        final_state -->|"是"| completed
        final_state -->|"否"| limited
    end

    subgraph consume["D. 使用、审计与改进"]
        direction TB
        status_stream["SSE 进度订阅\n只显示阶段、状态、安全摘要、时间戳\n不输出结论、SQL 或正文"]
        report_api["报告查询 API\n读取持久化、可审计的最终结果"]
        feedback["匿名反馈\n用于后续质量改进"]
        evaluation["固定 15 题评测\n检索、SQL 安全、人工语义评分"]
        status_stream --> report_api --> feedback
        report_api --> evaluation
    end

    start --> scope --> pii
    pii -->|"是"| reject_input
    pii -->|"否"| create_run
    create_run --> retrieve_business
    retrieve_business --> plan
    safe_query --> draft
    limited_data --> draft
    create_run -. "异步运行时可订阅" .-> status_stream
    completed --> report_api
    limited --> report_api

    prohibited["明确禁止：自动回复客户、关单、改优先级、派单、\n写数据库、调用任意外部服务、无限循环"]
    prohibited -. "不属于任何 Agent 节点能力" .-> start

    classDef decision fill:#fff7ed,stroke:#c2410c,color:#431407;
    classDef safe fill:#f0fdf4,stroke:#15803d,color:#14532d;
    classDef blocked fill:#fef2f2,stroke:#b91c1c,color:#450a0a;
    class pii,validate,repair_sql,review,revise_sql,revise_conclusion,final_state decision;
    class safe_query,report,completed,limited,report_api safe;
    class reject_input,audit_reject,prohibited blocked;
```

## 阅读说明

- 实线表示正常数据或控制流；虚线表示状态通知、约束或部署关系。
- `limited` 是受控失败或受限完成的诚实状态：例如 SQL 被拒绝两次后，系统仍可基于可追溯证据给出带限制说明的分析；它不等同于查询成功。
- SSE 只提供进度，最终结论必须通过持久化报告 API 获取。这样客户端断开、进程内事件缓存淘汰都不会篡改运行结果。
- 资源 CRUD 使用业务账号；分析 SQL 只能通过只读账号。迁移账号只用于 Alembic 维护，不会注入 FastAPI 运行时或任何 Agent。
