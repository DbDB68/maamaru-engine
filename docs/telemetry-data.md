# 结构化运行数据（Schema v1）

这套数据用于前端统计和后续智能建议。调用方不得解析中文运行日志；日志只给人看，
稳定机器字段统一来自 `%LOCALAPPDATA%/Maamaru*/logs/telemetry.db` 和以下 API。

## API

- `GET /api/data/summary?days=30`：时间窗口内的任务、OCR、事件聚合，并附当前库存、
  日课、远征、内番状态。
- `GET /api/data/events?limit=100&event_type=&script=`：最近的结构化玩法事件。
- `GET /api/data/ocr?limit=100&script=&matched=`：OCR 观测明细。

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
- `inventory.captured`

新增事件应使用 `领域.过去式动作`，payload 只放数据，不放展示文案。事件和 OCR 默认保留
90 天；当前状态 JSON 仍保留原有接口，便于旧前端渐进迁移。
