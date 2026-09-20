/** 模板工坊框选器的纯几何计算：手柄命中、拉边微调、帧边界钳制。
 *  全部在图像坐标系里算，不碰 DOM，方便单测。 */

export interface SelRect { x: number; y: number; w: number; h: number }

export type HandleId = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w'

/** 手柄屏幕边长（px），图像坐标里要除以 zoom 换算 */
export const HANDLE_SCREEN_PX = 8
/** 命中域：以手柄中心为圆心，屏幕像素半径换算到图像坐标 */
export const HANDLE_HIT_PX = 8
/** 微调最小尺寸 */
export const MIN_SEL_SIZE = 2

export const HANDLE_IDS: HandleId[] = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']

export const HANDLE_CURSORS: Record<HandleId, string> = {
  nw: 'nwse-resize', se: 'nwse-resize',
  ne: 'nesw-resize', sw: 'nesw-resize',
  n: 'ns-resize', s: 'ns-resize',
  e: 'ew-resize', w: 'ew-resize',
}

/** 八向手柄中心点（图像坐标） */
export function handlePoints(sel: SelRect): Record<HandleId, { x: number; y: number }> {
  const x2 = sel.x + sel.w
  const y2 = sel.y + sel.h
  const cx = sel.x + sel.w / 2
  const cy = sel.y + sel.h / 2
  return {
    nw: { x: sel.x, y: sel.y },
    n: { x: cx, y: sel.y },
    ne: { x: x2, y: sel.y },
    e: { x: x2, y: cy },
    se: { x: x2, y: y2 },
    s: { x: cx, y: y2 },
    sw: { x: sel.x, y: y2 },
    w: { x: sel.x, y: cy },
  }
}

/** 命中检测：point 为图像坐标，zoom 把屏幕像素命中域换算进图像坐标 */
export function hitHandle(sel: SelRect, point: { x: number; y: number }, zoom: number): HandleId | null {
  if (!sel || sel.w <= 0 || sel.h <= 0) return null
  const radius = HANDLE_HIT_PX / Math.max(zoom, 0.01)
  const points = handlePoints(sel)
  for (const id of HANDLE_IDS) {
    const p = points[id]
    if (Math.abs(point.x - p.x) <= radius && Math.abs(point.y - p.y) <= radius) return id
  }
  return null
}

/** 拉某个手柄得到新框：对边/对角锚定不动，不许交叉对穿（顶住成最小尺寸）。
 *  bounds 给了就把被拖的边钳在帧边界内。 */
export function applyResize(sel: SelRect, handle: HandleId, point: { x: number; y: number },
                            bounds?: { width: number; height: number }): SelRect {
  const east = sel.x + sel.w
  const south = sel.y + sel.h
  let x1 = sel.x
  let y1 = sel.y
  let x2 = east
  let y2 = south
  const px = bounds ? Math.min(Math.max(0, Math.round(point.x)), bounds.width) : Math.round(point.x)
  const py = bounds ? Math.min(Math.max(0, Math.round(point.y)), bounds.height) : Math.round(point.y)

  if (handle.includes('w')) {
    // 西边跟着指针走，东边锚定；拖过东边就顶住
    x1 = Math.min(px, east - MIN_SEL_SIZE)
  } else if (handle.includes('e')) {
    x2 = Math.max(px, sel.x + MIN_SEL_SIZE)
  }
  if (handle.includes('n')) {
    y1 = Math.min(py, south - MIN_SEL_SIZE)
  } else if (handle.includes('s')) {
    y2 = Math.max(py, sel.y + MIN_SEL_SIZE)
  }
  return { x: x1, y: y1, w: x2 - x1, h: y2 - y1 }
}

/** 整框钳进帧边界（新框拖拽 / 键盘微调用），返回整数坐标 */
export function clampRect(sel: SelRect, width: number, height: number): SelRect {
  const x = Math.min(Math.max(0, Math.round(sel.x)), width)
  const y = Math.min(Math.max(0, Math.round(sel.y)), height)
  return {
    x,
    y,
    w: Math.min(Math.round(sel.w), width - x),
    h: Math.min(Math.round(sel.h), height - y),
  }
}
