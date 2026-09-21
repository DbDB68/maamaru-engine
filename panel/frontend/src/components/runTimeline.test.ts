import { describe, expect, it } from 'vitest'
import { formatDuration, lineStatus, parseRun, parseRuns } from './runTimeline'
import type { LogEntry } from './runTimeline'

let nextId = 1
function entry(message: string, overrides: Partial<LogEntry> = {}): LogEntry {
  return { id: nextId++, ts: 1700000000 + nextId, run_id: 'run1', script: 'daily', message, ...overrides }
}

describe('lineStatus', () => {
  it('认 ✗/⚠/⏭/✓ 四种记号，其余是 info', () => {
    expect(lineStatus('✓ 已点击')).toBe('ok')
    expect(lineStatus('[A] ✗ 没找到按钮')).toBe('fail')
    expect(lineStatus('[A] ⚠️ 收尾失败（不影响跑）')).toBe('warn')
    expect(lineStatus('  内番: ⏭ 跳过（翻车即停）')).toBe('skip')
    expect(lineStatus('[NAV] 尝试打开目录 (第1次)')).toBe('info')
  })
})

describe('parseRun 步骤归并', () => {
  it('连续同 tag 的行归成一步，换 tag 开新步', () => {
    const run = parseRun('run1', 'daily', [
      entry('[远征] 收菜开始'),
      entry('[远征] ✓ 收了一队'),
      entry('[锻刀] 点火'),
      entry('[锻刀] ✓ 炉火正旺'),
    ])
    expect(run.steps.map(s => s.tag)).toEqual(['远征', '锻刀'])
    expect(run.steps[0].lines).toHaveLength(2)
    expect(run.steps[1].lines).toHaveLength(2)
  })

  it('无 tag 的行并入当前步骤（流程步骤的原始输出就是无前缀的）', () => {
    const run = parseRun('run1', 'custom_flow', [
      entry('[活动] ▶ 第 1/2 步：点公告'),
      entry('✓ 已点击 (640, 360)'),
      entry('✓ 已点安全区'),
    ])
    expect(run.steps).toHaveLength(1)
    expect(run.steps[0].lines).toHaveLength(3)
  })

  it('步骤状态取行内最严重：✓ 之后翻车就是 fail', () => {
    const run = parseRun('run1', 'daily', [
      entry('[远征] ✓ 一队归来'),
      entry('[远征] ⚠️ 结算屏没读到'),
      entry('[远征] ✗ 派遣失败'),
    ])
    expect(run.steps[0].status).toBe('fail')
    const warn = parseRun('run1', 'daily', [entry('[远征] ✓ 归来'), entry('[远征] ⚠️ 小状况')])
    expect(warn.steps[0].status).toBe('warn')
    const skip = parseRun('run1', 'daily', [entry('  远征: ⏭ 跳过（翻车即停）')])
    expect(skip.steps[0].status).toBe('skip')
  })

  it('NAV/ADB/MAA 噪音行不进时间线', () => {
    const run = parseRun('run1', 'daily', [
      entry('[NAV] 尝试打开目录 (第1次)'),
      entry('[ADB] 点击 (100, 200)'),
      entry('[MAA] 模板命中: 菜单'),
      entry('[远征] ✓ 收了一队'),
    ])
    expect(run.steps).toHaveLength(1)
    expect(run.steps[0].lines).toHaveLength(1)
  })

  it('步骤耗时取首行到末行的时间戳', () => {
    const run = parseRun('run1', 'daily', [
      entry('[远征] 开始', { ts: 1000 }),
      entry('[远征] ✓ 结束', { ts: 1025 }),
    ])
    expect(run.steps[0].startTs).toBe(1000)
    expect(run.steps[0].endTs).toBe(1025)
  })

  it('没有横幅时标题用首行摘要并剥掉前缀', () => {
    const run = parseRun('run1', 'daily', [entry('[远征] 正在收取归来奖励，照实记账')])
    expect(run.steps[0].title).toBe('正在收取归来奖励，照实记账')
  })
})

describe('parseRun 流程工坊步骤名', () => {
  it('「▶ 第 x/n 步：label」横幅切步，标题用老大起的名字', () => {
    const run = parseRun('r', 'custom_flow', [
      entry('[新活动] ▶ 开跑「新活动」，共 3 步'),
      entry('[新活动] ▶ 第 1/3 步：等活动入口'),
      entry('✓ 地标已就绪：event/入口.png'),
      entry('[新活动] ▶ 第 2/3 步：点入口'),
      entry('✓ 认到并点击模板'),
      entry('[新活动] ▶ 第 3/3 步：领奖'),
      entry('✗ 没找到可点的模板，没点'),
    ])
    expect(run.steps.map(s => s.title)).toEqual(['开跑「新活动」，共 3 步', '等活动入口', '点入口', '领奖'])
    expect(run.steps[2].status).toBe('ok')
    expect(run.steps[3].status).toBe('fail')
  })

  it('重试横幅的（翻车重试 x/y）角标不进标题', () => {
    const run = parseRun('r', 'custom_flow', [
      entry('[新活动] ▶ 第 1/2 步：点入口'),
      entry('[新活动] ▶ 第 1/2 步：点入口（翻车重试 1/2）'),
    ])
    expect(run.steps[1].title).toBe('点入口')
  })

  it('成绩单收进「总成绩单」步骤，收尾播报不另开步', () => {
    const run = parseRun('r', 'custom_flow', [
      entry('[新活动] ▶ 第 1/1 步：回家'),
      entry('========== 流程成绩单 =========='),
      entry('  回家: ✓'),
      entry('[新活动] 全部跑完，全绿'),
    ])
    const board = run.steps[run.steps.length - 1]
    expect(board.title).toBe('总成绩单')
    expect(board.lines.map(l => l.message)).toContain('[新活动] 全部跑完，全绿')
  })
})

describe('parseRun 工作流兼容', () => {
  it('「【工作流】▶ 第 N 块：label」同样切步', () => {
    const run = parseRun('r', 'workflow', [
      entry('【工作流】▶ 第 1 块：签到'),
      entry('[签到] ✓ 签到了'),
      entry('【工作流】▶ 第 2 块：万屋领免费礼包'),
      entry('[万屋] ✗ 未找到暖心礼包，停'),
    ])
    expect(run.steps.map(s => s.title)).toEqual(['签到', '万屋领免费礼包'])
    expect(run.steps[1].status).toBe('fail')
  })
})

describe('parseRun run 边界', () => {
  it('[脚本] 收尾行定终态且不进步骤', () => {
    const run = parseRun('r', 'daily', [
      entry('[远征] ✓ 收了一队'),
      entry('[脚本] 完成 — run r'),
    ])
    expect(run.ended).toBe(true)
    expect(run.endStatus).toBe('completed')
    expect(run.steps[0].lines.map(l => l.message)).not.toContain('[脚本] 完成 — run r')
  })

  it('手动停止/看门狗/异常各自映射终态', () => {
    expect(parseRun('r', 'daily', [entry('[脚本] 已手动停止（工人进程已杀）— run r')]).endStatus).toBe('stopped')
    expect(parseRun('r', 'daily', [entry('[脚本] 看门狗已处决卡死的工人进程 — run r')]).endStatus).toBe('watchdog')
    expect(parseRun('r', 'daily', [entry('[脚本] 工人进程异常退出（代码 1）— run r')]).endStatus).toBe('failed')
  })

  it('没有收尾行 = 还在跑', () => {
    const run = parseRun('r', 'daily', [entry('[远征] 正在收')])
    expect(run.ended).toBe(false)
    expect(run.endStatus).toBeNull()
  })
})

describe('parseRuns 分组', () => {
  it('按 run_id 分组，调度器不进时间线', () => {
    const runs = parseRuns([
      entry('[远征] A1', { run_id: 'aaa', script: 'expedition' }),
      entry('[脚本] 完成 — run aaa', { run_id: 'aaa', script: 'expedition' }),
      entry('[锻刀] B1', { run_id: 'bbb', script: 'smith' }),
      entry('⏳ 远征即将接管', { run_id: 'scheduler', script: 'expedition' }),
    ])
    expect(runs.map(r => r.runId)).toEqual(['aaa', 'bbb'])
    expect(runs[0].script).toBe('expedition')
    expect(runs[1].ended).toBe(false)
  })
})

describe('formatDuration', () => {
  it('秒/分/小时各档', () => {
    expect(formatDuration(800)).toBe('0.8 秒')
    expect(formatDuration(42000)).toBe('42 秒')
    expect(formatDuration(125000)).toBe('2 分 5 秒')
    expect(formatDuration(3600000)).toBe('1 小时 0 分')
  })
})
