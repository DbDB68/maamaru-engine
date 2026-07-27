# 本丸托管所（刀剑乱舞自动日课）

[!["maamaru-engine"](https://img.shields.io/badge/pip-maamaru--engine-purple)](https://pypi.org/project/maamaru-engine/)
[![License](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)

基于 MaaFramework 的刀剑乱舞自动托管。模拟器里开着游戏，脚本自己把每天的活儿干了，
成绩单打三个地方：看板「本丸托管所」、电脑桌面通知、手机 ntfy 推送。

## 快速安装

```bash
pip install maamaru-engine
```

需要额外下载资源包（OCR 模型 + 模板图）放在项目目录的 `resource/base/` 下：
→ [GitHub Releases 下载 resource.zip](https://github.com/你的用户名/maamaru/releases)

使用示例：

```python
from touken import MAAAdapter, ToukenAgent

maa = MAAAdapter(
    adb_path="D:/MUMU/.../adb.exe",
    adb_address="127.0.0.1:16384",
    resource_dir="./resource/base",
)

if not maa.init():
    exit(1)

agent = ToukenAgent("touken_config.json", maa)

for msg in agent.daily_stream():
    print(msg)
```

`touken_config.json` 需要按你的环境配置（模拟器分辨率 1280x720 已校准）。

## 每天自动跑什么

**每天 15:07**（定时任务「刀剑乱舞日课 · 每天15:07」）自动跑一键日课：

1. 登录（游戏没开会自己点图标冷启动，顺手关公告/推完结算动画）
2. 签到
3. 万屋领免费鸡蛋（暖心礼包）
4. 演练（认人避战：躲极短队和丙子椒林剑，赢够 3 场收工）
5. 远征（收菜 + 自动派回原图）
6. 内番（安排上工）
7. 锻刀（每日 3 炉，收完成的点空闲的）
8. 刀解（白名单一把）
9. 合成（白名单喂一把）
10. 出阵（联队战 3 圈，部队三）
11. 领任务奖励
12. 库存快照（给看板供数据）

炼糖和收件箱**不在**日课里，是要用了手动跑的（见下）。

## 手动使唤（在 W:\Maamaru 下）

一律用这个python：`./.venv/Scripts/python.exe`

| 命令 | 干啥 |
|---|---|
| `test_daily.py` | 手动跑一遍完整日课 |
| `test_sakura.py --team 1 --slot 1` | 刷花：队长单挑 1-1 刷疲劳到 100（队长满了会自动找疲劳<50的人换进来） |
| `test_sakura.py --team 1 --slot 1 --check` | 只读疲劳值，不动手 |
| `test_sugar.py` | 炼糖：收件箱清狗粮 + 习合循环，喂到邮件里没刀为止 |
| `test_raid.py` | 单测联队战 |
| `test_practice.py` | 单测演练 |
| `test_expedition.py` | 单测远征收菜 |
| `test_repair.py` | 单测手入（黑名单的不修） |
| `test_smith.py` | 单测锻刀+刀解 |
| `test_synthesize.py` | 单测合成 |
| `test_naihanka.py` | 单测内番 |
| `test_sortie.py` | 单测普通出阵 |

翻车了就再跑一遍——链路是幂等的，做过的步骤会自己跳过。

## 手机推送（ntfy）

- App：ntfy（蓝铃铛图标），订阅频道 `maamaru-honmaru-237a0e45cfae`
- 频道名就是密码，别外传；以后给别人用就一人开一个频道
- 日课跑完自动推成绩单：全绿 🎉，有翻车 ⚠️ 高优先级

## 看板（Kimi Work 里）

「本丸托管所」Canvas 两块面板，每 30 分钟自刷：
- **日课成绩单** — 读 `status/latest_report.json`
- **资源库存 · 本丸家底** — 读 `status/inventory.json` + 远征/内番倒计时

## 文件地图

```
maamaru-engine/              ← pip install maamaru-engine
├── touken/                  代码本体
│   ├── __init__.py          公开 API：ToukenAgent, MAAAdapter
│   ├── maa_adapter.py       底层：截图/点击/OCR/模板匹配
│   ├── navigator.py         中层：导航 + 弹窗处理（含全屏界面救援）
│   ├── agent.py             ToukenAgent 主类（多继承组装）
│   ├── sword_db.py          刀剑名册（认人用的）
│   ├── notify.py            ntfy 推送
│   ├── data/                静态数据（刀剑名册、远征收益表）
│   └── flows/               上层：每个玩法一个文件
├── resource/base/           资源包（OCR 模型 + 121 张模板图）
├── touken_config.json       总配置
├── test_*.py                使用示例 / 手动入口
├── status/                  运行时数据（成绩单/库存/远征记录）
├── debug/                   运行时日志
└── 玩法说明书.docx          游戏机制笔记
```

## 关键配置（touken_config.json）

- `daily.sortie` — 日课出阵：`{"mode":"raid","rounds":3}` 刷联队战；改 `"none"` 不打
- `daily.expedition_redispatch` — 远征收菜后自动派回原图（`"same"`）
- `raid.team_no` — 联队战用哪队（现在部队三）
- `notify` — ntfy 频道
- 刀解/合成白名单在 `touken/flows/smith.py` 顶部

## 作为 pip 包使用

```python
from touken import ToukenAgent, MAAAdapter

# 1. 连接模拟器
maa = MAAAdapter(
    adb_path="你的ADB路径",
    adb_address="模拟器地址",
    resource_dir="resource/base",
)
if not maa.init():
    exit(1)

# 2. 创建 Agent
agent = ToukenAgent("touken_config.json", maa)

# 3. 调用任意业务
for msg in agent.daily_stream():    # 一键日课
    print(msg)

for msg in agent.sakura_stream(team_no=1, slot=1):  # 刷花
    print(msg)

for msg in agent.status_snapshot_stream():  # 库存快照
    print(msg)
```

所有 `stream()` 方法都是 Python 生成器，逐条 yield 执行消息，
方便集成到任何前端（CLI / Web / QQ Bot / Telegram）。

## 安全规矩（写死在代码里的）

- 有重伤绝不出阵（会碎刀）
- 上锁的刀不会被刀解/习合选中——**用炼糖前把重要的刀锁好**
- 演练只打软柿子，极短队/丙子队绕着走
- 手入黑名单里的刀不修

## 翻车自救

1. 看 `status/latest_report.json` 哪步 ✗
2. 模拟器是不是关了：脚本不会自己开模拟器，只会开游戏
3. 界面卡住了：手动点回本丸再跑一遍（幂等）
4. 模板/OCR 突然认不出：检查模拟器分辨率是不是 1280x720、缩放 100%
