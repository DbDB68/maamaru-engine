# 结构化运行数据（Schema v1）

这套数据用于前端统计和后续智能建议。调用方不得解析中文运行日志；日志只给人看，
稳定机器字段统一来自 `%LOCALAPPDATA%/Maamaru*/logs/telemetry.db` 和以下 API。

## API

- `GET /api/data/summary?days=30`：时间窗口内的任务、OCR、事件聚合，并附当前库存、
  日课、远征、内番状态。
- `GET /api/data/events?limit=100&event_type=&script=`：最近的结构化玩法事件。
- `GET /api/data/ocr?limit=100&script=&matched=`：OCR 观测明细。
- `GET /api/data/resource-ledger?days=7` 或 `?from=<ts>&to=<ts>`：资源总账（见下文），
  from/to（Unix 秒）优先于 days，days 默认 7。聚合全部在服务端完成，
  前端不要拉原始 events 自己算。

所有响应都带 `schema_version`。前端遇到不认识的更高版本时，应保留未知字段，
不要因新增字段报错。

## OCR observation

```json
{
  "id": 1,
  "ts": 1786600000.0,
  "run_id": "abc123",
  "script": "osaka",
  "kind": "match",
  "expected": "当前层数",
  "match_mode": "contains",
  "matched": true,
  "roi": [825, 270, 455, 85],
  "tokens": [{
    "text": "当前层数",
    "score": 0.98,
    "center": [1000, 310],
    "box": [900, 290, 200, 40]
  }],
  "error": null
}
```

`kind=all` 没有期望值，`matched` 为 `null`。这里只保存文字和识别元数据，不保存截图。

## Event

```json
{
  "id": 1,
  "ts": 1786600000.0,
  "run_id": "abc123",
  "script": "osaka",
  "event_type": "osaka.floor_completed",
  "payload": {"completed": 34, "target": 120, "selected_floor": 88}
}
```

当前事件类型：

- `game_update.detected`、`game_update.recovered`
- `osaka.floor_completed`
- `repair.queued`、`repair.skipped`、`repair.session_completed`
- `team_record.saved`、`equipment.restored`
- `injury_warning.denied`
- `practice.result`
- `sortie.completed`、`raid.round_completed`
- `pumpkin.sortie_completed`、`pumpkin.board_completed`、`pumpkin.token_used`、`pumpkin.sword_obtained`
- `forge.started`、`forge.collected`
- `expedition.dispatched`、`expedition.settled`
- `task_rewards.claimed`
- `inventory.captured`、`inventory.peek`、`osaka.koban_session`
- `resource.change`（通用资源流水，见下文）
- `yosari.ticket_refilled`（归城提灯补充完成；金额识别失败时仍保留事实）

新增事件应使用 `领域.过去式动作`，payload 只放数据，不放展示文案。事件和 OCR 默认保留
90 天；当前状态 JSON 仍保留原有接口，便于旧前端渐进迁移。

## 资源总账（resource-ledger，schema_version 1）

`GET /api/data/resource-ledger?days=7` / `?from=<ts>&to=<ts>`，聚合窗口内八种资源的账目。
资源全集（顺序固定）：木炭、玉钢、冷却材、砥石、小判、甲州金、委托符、加速符。

顶层结构：

```json
{
  "schema_version": 1,
  "generated_at": 1787219985.79,
  "window": {"from": 1786615185.79, "to": 1787219985.79,
             "timezone": "Asia/Shanghai", "days": 7.0},
  "per_resource": [{
    "resource": "小判", "opening": 549656, "closing": 788506,
    "total_delta": 238850, "attributed_delta": 43000, "unattributed_delta": 195850,
    "observation_count": 24, "confidence": "low"
  }],
  "daily_series": [{
    "date": "2026-08-20", "resource": "小判",
    "opening": 745056, "closing": 788506,
    "total_delta": 43450, "attributed_delta": 42850, "unattributed_delta": 600,
    "observation_count": 2, "confidence": "high",
    "gap_ids": [], "attribution_ids": ["a2"]
  }],
  "gaps": [{
    "id": "gap-1786768892-1786791169", "from": 1786768892.0, "to": 1786791169.0,
    "resources": {"小判": -1500},
    "reason": "no_observation", "human_report_ids": [2]
  }],
  "attributions": [{
    "id": "a2", "ts": 1787150000.0, "resource": "小判", "delta": 42850,
    "source": "osaka.koban_session", "script": "osaka", "run_id": "abc123",
    "event_id": 123, "label": "挖地小判 +42850", "confidence": "confirmed"
  }]
}
```

### 核心语义

- **total_delta 保留符号、禁止截断**：恒满足 `total = attributed + unattributed`，
  三者可正可负（confirmed 收入 +100、净变化 +10 → 未归因 −90）。
- **opening/closing**：opening = 窗口（或当日）前最近一次观察，没有窗前基线则用
  窗口内首观察；closing = 窗口（或当日）内末次观察。观察不足形成不了 pair 时
  `total_delta = null`（不是 0），但 confirmed 明细仍保留在 `attributions` 里。
- **daily_series**：按 Asia/Shanghai 日期分桶；跨日 run 按观察发生日记账，
  不按 run 归属日。

### 观察点来源与优先级

| 来源 | 覆盖资源 | 优先级 |
|---|---|---|
| `osaka.koban_session` 的 before/after（读游戏界面真数值） | 小判 | 3（最高） |
| `inventory.captured` 的 resources（任何 phase 都算观察） | 全部 8 项 | 2 |
| `inventory.peek` | 顶栏五资源（木炭/玉钢/冷却材/砥石/甲州金） | 1 |

`inventory.peek` **永远不含小判/委托符/加速符**（契约固定），聚合层按白名单过滤，
即使脏 payload 带了小判也不许污染小判观察链。

**去重规则**：同一资源、时间相差 5 秒内且数值一致的多来源观察 = 同一点，只算一次，
保留全部证据 event id，来源升到最高优先级。同一事件的 before/after 本来就该不同值，
不算冲突；不同来源贴脸读数不一致记 `conflicting_evidence` 缺口并降低置信度。

### 归因（attributions）

窗口内每条可确认资源变化一条记录。当前 confirmed 来源：

- `osaka.koban_session`：小判 `delta`（读数差值）。
- `repair.session_completed`：加速符 `−speedups`。
- `resource.change` / `yosari.ticket_refill`：补充归城提灯时，以购买页前后余额确认小判支出。
- `resource.change` / `expedition.settlement`：远征结算页 OCR 确认的四项基础资源收益。

**双写兼容**：未来玩法流程可发射 `resource.change` 事件；payload 带
`source_event_id` 指向旧事件 id 时，聚合层跳过旧事件那一份，不重复聚合。

```json
{"event_type": "resource.change", "run_id": "可选", "script": "osaka",
 "resource": "小判", "delta": 42850, "before": 745656, "after": 788506,
 "source": "osaka.koban_session", "source_event_id": 123,
 "attribution": "confirmed|observed|estimated|unknown",
 "evidence": "direct_before_after|settlement_ocr|rule_estimate|...",
 "note": "可选"}
```

### 缺口（gaps）与置信度

- `no_observation`：相邻快照跨 run 有差值（沿用 `inventory_gaps` 的配对语义，
  即前一条 phase 为 after/无、后一条为 before 且 run 不同），说明两段观察之间
  的账目没有覆盖。gap id 由边界时间戳生成，稳定可引用。
- `human_reported`：窗口内的人工报备（`human_reports` 表）——能通过
  `gap_key` 或时间落入挂到某个 no_observation 缺口上就挂上去
  （填入 `human_report_ids`），挂不上就单独成条。**人工报备只降置信度，
  不改写库存数值**。
- `conflicting_evidence`：同资源 5 秒内不同来源读数不一致。

confidence 规则（per_resource 和 daily_series 通用）：

- `high`：有 confirmed 归因覆盖且观察链完整（opening/closing 都可靠、无缺口）。
- `medium`：只有观察差值、无归因覆盖。
- `low`：观察缺失 / 有缺口（含人工报备）/ 证据冲突。
