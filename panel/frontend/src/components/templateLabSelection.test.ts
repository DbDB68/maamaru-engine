import { describe, expect, it } from 'vitest'
import { applyResize, clampRect, handlePoints, hitHandle, MIN_SEL_SIZE } from './templateLabSelection'

const SEL = { x: 100, y: 100, w: 200, h: 100 } // 东边 300，南边 200

describe('手柄点位', () => {
  it('八向手柄落在四角和四边中点', () => {
    const p = handlePoints(SEL)
    expect(p.nw).toEqual({ x: 100, y: 100 })
    expect(p.se).toEqual({ x: 300, y: 200 })
    expect(p.n).toEqual({ x: 200, y: 100 })
    expect(p.w).toEqual({ x: 100, y: 150 })
  })
})

describe('手柄命中', () => {
  it('命中域按 zoom 换算：1 倍时 ±8 图像像素内算命中', () => {
    expect(hitHandle(SEL, { x: 105, y: 105 }, 1)).toBe('nw')
    expect(hitHandle(SEL, { x: 300, y: 154 }, 1)).toBe('e')
    expect(hitHandle(SEL, { x: 200, y: 120 }, 1)).toBeNull() // 边中点垂直偏 20px
    expect(hitHandle(SEL, { x: 150, y: 150 }, 1)).toBeNull() // 框内部不算
  })

  it('4 倍缩放时命中域缩到 ±2 图像像素', () => {
    expect(hitHandle(SEL, { x: 102, y: 101 }, 4)).toBe('nw')
    expect(hitHandle(SEL, { x: 106, y: 101 }, 4)).toBeNull()
  })

  it('没有框或框为空时不命中', () => {
    expect(hitHandle({ x: 0, y: 0, w: 0, h: 0 }, { x: 0, y: 0 }, 1)).toBeNull()
  })
})

describe('拉边微调', () => {
  it('拖东边只动宽，西/北/南锚定', () => {
    expect(applyResize(SEL, 'e', { x: 250, y: 999 })).toEqual({ x: 100, y: 100, w: 150, h: 100 })
  })

  it('拖西北角两边一起动，东南角锚定', () => {
    expect(applyResize(SEL, 'nw', { x: 80, y: 60 })).toEqual({ x: 80, y: 60, w: 220, h: 140 })
  })

  it('边不许交叉对穿：拖过对边顶住最小尺寸', () => {
    const r = applyResize(SEL, 'e', { x: 50, y: 150 }) // 东边拖过西边
    expect(r).toEqual({ x: 100, y: 100, w: MIN_SEL_SIZE, h: 100 })
    const r2 = applyResize(SEL, 'w', { x: 400, y: 150 }) // 西边拖过东边
    expect(r2).toEqual({ x: 300 - MIN_SEL_SIZE, y: 100, w: MIN_SEL_SIZE, h: 100 })
  })

  it('给了边界就把被拖的边钳进帧内', () => {
    const bounds = { width: 1280, height: 720 }
    expect(applyResize(SEL, 'e', { x: 2000, y: 150 }, bounds)).toEqual({ x: 100, y: 100, w: 1180, h: 100 })
    expect(applyResize(SEL, 'nw', { x: -50, y: -50 }, bounds)).toEqual({ x: 0, y: 0, w: 300, h: 200 })
  })
})

describe('整框钳制', () => {
  it('出界的框被拉回帧内并截断宽高', () => {
    expect(clampRect({ x: -10, y: 5, w: 50, h: 50 }, 1280, 720)).toEqual({ x: 0, y: 5, w: 50, h: 50 })
    expect(clampRect({ x: 1200, y: 700, w: 200, h: 100 }, 1280, 720)).toEqual({ x: 1200, y: 700, w: 80, h: 20 })
  })

  it('反向拖出的负宽高框由调用方先转正，这里只负责钳边界', () => {
    expect(clampRect({ x: 10.4, y: 10.6, w: 100.2, h: 99.8 }, 1280, 720)).toEqual({ x: 10, y: 11, w: 100, h: 100 })
  })
})
