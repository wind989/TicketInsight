# TicketInsight API 使用边界

## 分析进度 SSE

`POST /api/v1/analysis-runs/async` 只创建一次固定分析运行，返回 `202` 与：

```json
{"id":"<run_id>","status":"running","events_url":"/api/v1/analysis-runs/<run_id>/events"}
```

使用 `GET /api/v1/analysis-runs/{run_id}/events` 订阅 `text/event-stream`。事件类型为 `progress`，其
`data` 严格只有以下五个字段：

```json
{"run_id":"<run_id>","stage":"query_completed","status":"completed","summary":"Bounded read-only query completed.","timestamp":"<UTC ISO-8601>"}
```

阶段仅表达受控状态：检索开始/完成、SQL 在执行前被拒绝、一次 SQL 修订开始、查询完成、草稿完成、复核完成、分析完成或失败。摘要来自代码中的有限白名单，不能携带原始 SQL、工单正文、知识正文、个人信息、模型原始输出、密钥、授权头、连接串或最终结论。

事件在进程内按运行最多缓存 32 条，并以低频轮询和心跳维持连接。客户端主动断开只结束这条订阅，后台分析使用独立数据库会话继续运行；完成、受限或失败都会发送一个终态。进程重启后，缓存可能丢失，订阅者最多收到由持久化运行状态生成的一条安全终态。

未知运行 ID 返回 `404`。当前本机原型尚无认证；接入认证后，无权访问该运行的请求也必须返回相同的 `404`，不得透露运行是否存在。

SSE 不是报告接口，也不提供模型逐字流。收到终态后，使用 `GET /api/v1/analysis-runs/{run_id}` 获取既有的、已持久化且可审计的最终报告。
