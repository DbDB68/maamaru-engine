<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import type { TemplateLabDraft, TemplateLabFrame, TemplateLabSession, TemplateLabStatus, TemplateLabVerifyResult } from '../types'
import PixelControl from './PixelControl.vue'

interface SelRect { x: number; y: number; w: number; h: number }

const status = ref<TemplateLabStatus | null>(null)
const message = ref('')
const errorMsg = ref('')

// ---- 抓帧 ----
const captureCount = ref(10)
const captureInterval = ref(500)
const capturing = ref(false)
const captureNote = ref('')
const captureErrors = ref<string[]>([])
const sessions = ref<TemplateLabSession[]>([])
const historyPick = ref('')
const currentSession = ref('')
const frames = ref<TemplateLabFrame[]>([])
const currentIdx = ref(0)

// ---- 框选 ----
const zoom = ref(1)
const lockSelection = ref(false)
const selection = ref<SelRect | null>(null)
const dragging = ref(false)
const canvasRef = ref<HTMLCanvasElement | null>(null)
const previewRef = ref<HTMLCanvasElement | null>(null)
let dragStart: { x: number; y: number } | null = null
let renderToken = 0

const frameMeta = computed(() => frames.value[currentIdx.value] ?? null)
const canvasStyle = computed(() => {
  const meta = frameMeta.value
  if (!meta) return { width: '0px', height: '0px' }
  return { width: `${meta.width * zoom.value}px`, height: `${meta.height * zoom.value}px` }
})
const selText = computed(() => {
  const sel = selection.value
  return sel && sel.w > 0 && sel.h > 0 ? `x ${sel.x}，y ${sel.y}，宽 ${sel.w}，高 ${sel.h}` : '还没框，按住鼠标拖一个'
})

// ---- 导出与验分 ----
const draftName = ref('')
const drafts = ref<TemplateLabDraft[]>([])
const draftPick = ref('')
const verifySessions = ref<string[]>([])
const threshold = ref(0.7)
const verifying = ref(false)
const verifyResult = ref<TemplateLabVerifyResult | null>(null)
const adoptTarget = ref('')
const adoptBusy = ref(false)
const adoptPath = ref('')
const cropBusy = ref(false)

function fail(e: unknown) {
  errorMsg.value = e instanceof Error && e.message ? e.message : '操作失败，请检查后端连接'
}

const frameUrl = (session: string, idx: number) => api.templateLabFrameUrl(session, idx)

const imageCache = new Map<string, Promise<HTMLImageElement>>()
function loadFrameImage(session: string, idx: number): Promise<HTMLImageElement> {
  const key = `${session}:${idx}`
  let pending = imageCache.get(key)
  if (!pending) {
    pending = new Promise((resolve, reject) => {
      const img = new Image()
      img.onload = () => resolve(img)
      img.onerror = () => {
        imageCache.delete(key)
        reject(new Error(`帧 ${idx} 加载失败`))
      }
      img.src = frameUrl(session, idx)
    })
    imageCache.set(key, pending)
  }
  return pending
}

// ---- 数据加载 ----
async function loadSessions() {
  try {
    const data = await api.templateLabSessions()
    sessions.value = data.sessions
  } catch (e) { fail(e) }
}

async function loadDrafts() {
  try {
    const data = await api.templateLabDrafts()
    drafts.value = data.drafts
    if (draftPick.value && !data.drafts.some(d => d.name === draftPick.value)) draftPick.value = ''
  } catch (e) { fail(e) }
}

async function capture() {
  const count = Math.max(1, Math.min(120, Math.round(Number(captureCount.value) || 10)))
  const interval = Math.max(50, Math.round(Number(captureInterval.value) || 500))
  capturing.value = true
  captureNote.value = '抓取中……保持模拟器画面稳定'
  captureErrors.value = []
  errorMsg.value = ''
  try {
    const result = await api.templateLabCapture(count, interval)
    captureErrors.value = result.errors
    message.value = `抓到 ${result.frames.length} 帧（会话 ${result.session}）`
    await loadSessions()
    await applySession({ id: result.session, frames: result.frames })
    historyPick.value = result.session
    verifySessions.value = [result.session]
  } catch (e) { fail(e) } finally {
    capturing.value = false
    captureNote.value = ''
  }
}

function applySession(session: TemplateLabSession) {
  currentSession.value = session.id
  frames.value = session.frames
  currentIdx.value = 0
  selection.value = null
}

function loadHistory() {
  const picked = sessions.value.find(s => s.id === historyPick.value)
  if (!picked) return
  applySession(picked)
  verifySessions.value = [picked.id]
  message.value = `已加载会话 ${picked.id}（${picked.frames.length} 帧）`
}

function pickFrame(i: number) {
  if (i === currentIdx.value) return
  currentIdx.value = i
  if (!lockSelection.value) selection.value = null
}

function flipFrame(delta: number) {
  if (!frames.value.length) return
  const next = (currentIdx.value + delta + frames.value.length) % frames.value.length
  pickFrame(next)
}

// ---- 画布绘制 ----
async function renderCanvas() {
  const canvas = canvasRef.value
  if (!canvas) return
  const token = ++renderToken
  const meta = frameMeta.value
  if (!currentSession.value || !meta) {
    canvas.width = 0
    canvas.height = 0
    return
  }
  try {
    const img = await loadFrameImage(currentSession.value, meta.idx)
    if (token !== renderToken) return
    if (canvas.width !== img.naturalWidth) canvas.width = img.naturalWidth
    if (canvas.height !== img.naturalHeight) canvas.height = img.naturalHeight
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.imageSmoothingEnabled = false
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(img, 0, 0)
    const sel = selection.value
    if (sel && sel.w > 0 && sel.h > 0) {
      ctx.fillStyle = 'rgba(212, 160, 23, 0.12)'
      ctx.fillRect(sel.x, sel.y, sel.w, sel.h)
      ctx.strokeStyle = '#d4a017'
      ctx.lineWidth = Math.max(1, 1.5)
      ctx.strokeRect(sel.x + 0.5, sel.y + 0.5, sel.w - 1, sel.h - 1)
    }
  } catch (e) { fail(e) }
}

async function renderPreview() {
  const canvas = previewRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const sel = selection.value
  if (!sel || sel.w < 1 || sel.h < 1 || !currentSession.value || !frameMeta.value) {
    canvas.width = 0
    canvas.height = 0
    return
  }
  try {
    const img = await loadFrameImage(currentSession.value, frameMeta.value.idx)
    const scale = Math.min(140 / sel.w, 140 / sel.h, 4)
    canvas.width = Math.max(1, Math.round(sel.w * scale))
    canvas.height = Math.max(1, Math.round(sel.h * scale))
    ctx.imageSmoothingEnabled = false
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(img, sel.x, sel.y, sel.w, sel.h, 0, 0, canvas.width, canvas.height)
  } catch { /* 预览失败不打扰主流程 */ }
}

watch([currentIdx, currentSession], () => { renderCanvas() })
watch(selection, () => { renderCanvas(); renderPreview() })

// ---- 鼠标框选 ----
function toImageCoords(e: MouseEvent) {
  const canvas = canvasRef.value
  if (!canvas || !canvas.width) return { x: 0, y: 0 }
  const rect = canvas.getBoundingClientRect()
  return {
    x: (e.clientX - rect.left) * (canvas.width / rect.width),
    y: (e.clientY - rect.top) * (canvas.height / rect.height),
  }
}

function clampSel(sel: SelRect): SelRect {
  const meta = frameMeta.value
  if (!meta) return sel
  const x = Math.min(Math.max(0, Math.round(sel.x)), meta.width)
  const y = Math.min(Math.max(0, Math.round(sel.y)), meta.height)
  return {
    x,
    y,
    w: Math.min(Math.round(sel.w), meta.width - x),
    h: Math.min(Math.round(sel.h), meta.height - y),
  }
}

function onMouseDown(e: MouseEvent) {
  if (!frameMeta.value) return
  const p = toImageCoords(e)
  dragStart = p
  selection.value = { x: Math.round(p.x), y: Math.round(p.y), w: 0, h: 0 }
  dragging.value = true
}

function onMouseMove(e: MouseEvent) {
  if (!dragging.value || !dragStart) return
  const p = toImageCoords(e)
  selection.value = clampSel({
    x: Math.min(dragStart.x, p.x),
    y: Math.min(dragStart.y, p.y),
    w: Math.abs(p.x - dragStart.x),
    h: Math.abs(p.y - dragStart.y),
  })
}

function onMouseUp(e: MouseEvent) {
  if (!dragging.value) return
  onMouseMove(e)
  dragging.value = false
  dragStart = null
}

function nudgeSelection(dx: number, dy: number) {
  const sel = selection.value
  const meta = frameMeta.value
  if (!sel || !meta) return
  selection.value = clampSel({ ...sel, x: sel.x + dx, y: sel.y + dy })
}

// ---- 键盘：方向键微调 / 锁定后翻帧 ----
function onKeyDown(e: KeyboardEvent) {
  const target = e.target as HTMLElement | null
  if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable)) return
  if (!frames.value.length) return
  if (lockSelection.value && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
    e.preventDefault()
    flipFrame(e.key === 'ArrowRight' ? 1 : -1)
    return
  }
  if (!selection.value) return
  const step = e.shiftKey ? 10 : 1
  const dirs: Record<string, [number, number]> = {
    ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step],
  }
  const dir = dirs[e.key]
  if (dir) {
    e.preventDefault()
    nudgeSelection(dir[0], dir[1])
  }
}

// ---- 草稿 / 验分 / 采用 ----
async function saveDraft() {
  const name = draftName.value.trim()
  const sel = selection.value
  if (!name) { errorMsg.value = '先给模板起个名字'; return }
  if (!sel || sel.w < 2 || sel.h < 2 || !currentSession.value || !frameMeta.value) {
    errorMsg.value = '先在图上框一块区域（至少 2×2）'
    return
  }
  cropBusy.value = true
  errorMsg.value = ''
  try {
    const result = await api.templateLabCrop({
      session: currentSession.value, frame: frameMeta.value.idx,
      x: sel.x, y: sel.y, w: sel.w, h: sel.h, name,
    })
    message.value = `草稿「${result.draft.name}」已保存（${result.draft.width}×${result.draft.height}）`
    draftPick.value = result.draft.name
    await loadDrafts()
  } catch (e) { fail(e) } finally { cropBusy.value = false }
}

function toggleVerifySession(id: string, on: boolean) {
  verifySessions.value = on ? [...verifySessions.value, id] : verifySessions.value.filter(s => s !== id)
}

async function runVerify() {
  const draft = draftPick.value
  if (!draft) { errorMsg.value = '先选一个草稿'; return }
  if (!verifySessions.value.length) { errorMsg.value = '至少勾一个会话'; return }
  const th = Math.min(1, Math.max(0, Number(threshold.value)))
  verifying.value = true
  errorMsg.value = ''
  try {
    verifyResult.value = await api.templateLabVerify(draft, verifySessions.value, th)
  } catch (e) { fail(e) } finally { verifying.value = false }
}

async function adopt() {
  const draft = draftPick.value
  const target = adoptTarget.value.trim()
  if (!draft) { errorMsg.value = '先选一个草稿'; return }
  if (!target) { errorMsg.value = '填目标文件名（会落到 resource/base/image/）'; return }
  if (!window.confirm(`确认把草稿「${draft}」采用为正式模板「${target}」？\n这会写入模板目录${status.value?.ledger_mode ? '（账册模式）' : ''}，原有同名文件会先备份。`)) return
  adoptBusy.value = true
  errorMsg.value = ''
  try {
    const result = await api.templateLabAdopt(draft, target)
    adoptPath.value = `已落盘：${result.path}${result.backup ? `（备份：${result.backup}）` : ''}`
    message.value = `「${target}」已采用`
  } catch (e) { fail(e) } finally { adoptBusy.value = false }
}

onMounted(async () => {
  window.addEventListener('keydown', onKeyDown)
  try {
    status.value = await api.templateLabStatus()
  } catch { /* 后端没上线时状态条留空 */ }
  await Promise.all([loadSessions(), loadDrafts()])
  if (sessions.value.length) {
    historyPick.value = sessions.value[0].id
    applySession(sessions.value[0])
    verifySessions.value = [sessions.value[0].id]
  }
  renderCanvas()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeyDown)
})
</script>

<template>
  <div class="template-lab">
    <section class="lab-card">
      <h3>抓帧</h3>
      <p class="lab-hint">
        从模拟器显存抓无损运行帧。状态：
        <template v-if="status">
          <b v-if="status.adb_ready" class="lab-ok">连接正常</b>
          <b v-else class="lab-bad">模拟器未连接</b>
          <i v-if="status.ledger_mode">（账册模式）</i>
        </template>
        <template v-else>后端未响应</template>
      </p>
      <div class="lab-row">
        <label>数量<PixelControl v-model="captureCount" type="number" numeric :min="1" :max="120" /></label>
        <label>间隔毫秒<PixelControl v-model="captureInterval" type="number" numeric :min="50" /></label>
        <button class="primary" :disabled="capturing" @click="capture">{{ capturing ? '抓取中……' : '抓一组原图' }}</button>
        <span v-if="captureNote" class="lab-note">{{ captureNote }}</span>
      </div>
      <p v-if="captureErrors.length" class="lab-warn">抓取有缺帧：{{ captureErrors.join('；') }}</p>
      <div class="lab-row">
        <label>历史会话<PixelControl v-model="historyPick" as="select" @change="loadHistory">
          <option value="" disabled>选一个会话重新加载</option>
          <option v-for="s in sessions" :key="s.id" :value="s.id">{{ s.id }}（{{ s.frames.length }} 帧）</option>
        </PixelControl></label>
      </div>
      <div v-if="frames.length" class="lab-thumbs">
        <button v-for="(f, i) in frames" :key="f.idx" type="button" class="lab-thumb" :class="{ active: i === currentIdx }" @click="pickFrame(i)">
          <img :src="frameUrl(currentSession, f.idx)" :alt="`帧 ${f.idx}`" loading="lazy" />
          <span>#{{ f.idx }}</span>
        </button>
      </div>
      <p v-else class="lab-hint">还没有帧，先抓一组，或从历史会话里挑一个。</p>
    </section>

    <section v-if="frameMeta" class="lab-card">
      <h3>框选 <small>第 {{ frameMeta.idx }} 帧 · {{ frameMeta.width }}×{{ frameMeta.height }}</small></h3>
      <div class="lab-row">
        <div class="lab-zoom" role="group" aria-label="缩放">
          <button v-for="z in [1, 2, 4]" :key="z" type="button" :class="{ active: zoom === z }" @click="zoom = z">{{ z * 100 }}%</button>
        </div>
        <label class="lab-check"><input v-model="lockSelection" type="checkbox" />锁定框选（←/→ 翻帧框不动）</label>
      </div>
      <div class="lab-canvas-scroll">
        <canvas
          ref="canvasRef"
          class="lab-canvas"
          :style="canvasStyle"
          @mousedown.prevent="onMouseDown"
          @mousemove="onMouseMove"
          @mouseup="onMouseUp"
          @mouseleave="onMouseUp"
        />
      </div>
      <div class="lab-row lab-row-bottom">
        <p class="lab-hint">框：{{ selText }}。方向键微调 1px（Shift=10px）<template v-if="lockSelection">；锁定中，←/→ 直接翻帧</template></p>
        <div class="lab-preview-box">
          <span class="lab-hint">框内预览</span>
          <canvas ref="previewRef" class="lab-preview" />
        </div>
      </div>
    </section>

    <section class="lab-card">
      <h3>导出与验分</h3>
      <div class="lab-row">
        <label>模板名<PixelControl v-model="draftName" placeholder="例如 battle_result_victory" /></label>
        <button class="primary" :disabled="cropBusy" @click="saveDraft">{{ cropBusy ? '保存中……' : '保存草稿' }}</button>
      </div>
      <div class="lab-row">
        <label>草稿<PixelControl v-model="draftPick" as="select">
          <option value="" disabled>选草稿</option>
          <option v-for="d in drafts" :key="d.name" :value="d.name">{{ d.name }}（{{ d.width }}×{{ d.height }}）</option>
        </PixelControl></label>
        <img v-if="draftPick" class="lab-draft-preview" :src="api.templateLabDraftUrl(draftPick)" :alt="draftPick" />
      </div>
      <div class="lab-row">
        <label>阈值<PixelControl v-model="threshold" type="number" numeric :min="0" :max="1" :step="0.05" /></label>
        <button class="primary" :disabled="verifying" @click="runVerify">{{ verifying ? '验分中……' : '批量验分' }}</button>
      </div>
      <fieldset class="lab-sessions">
        <legend>拿去验分的会话</legend>
        <label v-for="s in sessions" :key="s.id" class="lab-check">
          <input type="checkbox" :checked="verifySessions.includes(s.id)" @change="toggleVerifySession(s.id, ($event.target as HTMLInputElement).checked)" />
          {{ s.id }}（{{ s.frames.length }} 帧）
        </label>
        <p v-if="!sessions.length" class="lab-hint">还没有会话。</p>
      </fieldset>
      <div v-if="verifyResult" class="lab-verify">
        <p class="lab-hint">「{{ verifyResult.draft }}」在阈值 {{ verifyResult.threshold }} 下：{{ verifyResult.results.filter(r => r.hit).length }}/{{ verifyResult.results.length }} 帧命中</p>
        <div v-if="verifyResult.results.length" class="lab-table-scroll">
          <table class="lab-table">
            <thead><tr><th>会话</th><th>帧</th><th>分数</th><th>位置</th><th>命中</th></tr></thead>
            <tbody>
              <tr v-for="(r, i) in verifyResult.results" :key="i">
                <td>{{ r.session }}</td>
                <td>#{{ r.frame }}</td>
                <td :class="r.hit ? 'lab-score-hit' : 'lab-score-miss'">{{ r.score.toFixed(3) }}</td>
                <td>({{ r.loc.x }}, {{ r.loc.y }})</td>
                <td>{{ r.hit ? '✓' : '✗' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <ul v-if="verifyResult.confusion.length" class="lab-confusion">
          <li v-for="(c, i) in verifyResult.confusion" :key="i">
            撞车：会话 {{ c.session }} 第 {{ c.frame }} 帧被「{{ c.other_draft }}」以 {{ c.other_score.toFixed(3) }} 分抢走（高出 {{ c.margin.toFixed(3) }}）
          </li>
        </ul>
      </div>
      <div class="lab-row">
        <label>目标文件名<PixelControl v-model="adoptTarget" placeholder="落盘到模板目录的文件名" /></label>
        <button class="primary" :disabled="adoptBusy" @click="adopt">{{ adoptBusy ? '采用中……' : '采用为正式模板' }}</button>
      </div>
      <p v-if="adoptPath" class="lab-ok">{{ adoptPath }}</p>
    </section>

    <p v-if="message" class="inline-message">{{ message }}</p>
    <p v-if="errorMsg" class="lab-warn">{{ errorMsg }}</p>
  </div>
</template>

<style scoped>
.template-lab { display: grid; gap: 14px; align-content: start; min-width: 0; padding: 4px 2px 12px; }
.lab-card { display: grid; gap: 10px; align-content: start; padding: 14px 16px; background: var(--paper-card); border: 1px solid var(--paper-line); border-radius: var(--r-lg); }
.lab-card h3 { margin: 0; font-size: 16px; }
.lab-card h3 small { margin-left: 8px; color: var(--ink-dim); font-size: 12px; font-weight: 400; }
.lab-hint { margin: 0; color: var(--ink-dim); font-size: 12px; }
.lab-note { color: var(--fox-gold-deep); font-size: 12px; }
.lab-ok { color: #426047; font-size: 12px; font-weight: 700; }
.lab-bad { color: #9f3d28; font-size: 12px; font-weight: 700; }
.lab-warn { margin: 0; padding: 9px 12px; color: #9f3d28; background: color-mix(in srgb, #f4dfd7 68%, var(--paper-card)); border: 1px solid #d8a195; border-radius: 8px; font-size: 12px; }
.lab-row { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 12px; }
.lab-row label { display: flex; flex-direction: column; gap: 5px; font-size: 12px; font-weight: 700; }
.lab-row label :deep(.pixel-control) { width: 170px; }
.lab-check { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 400; }
.lab-zoom { display: flex; gap: 0; border: 1px solid var(--line-strong); border-radius: var(--r-sm); overflow: hidden; }
.lab-zoom button { padding: 7px 12px; background: var(--paper); border: 0; border-right: 1px solid var(--line-strong); }
.lab-zoom button:last-child { border-right: 0; }
.lab-zoom button.active { color: #fffaf0; background: var(--fox-gold-deep); }
.lab-thumbs { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px; }
.lab-thumb { display: grid; gap: 2px; padding: 4px; place-items: center; background: var(--paper); border: 2px solid var(--paper-line); border-radius: 6px; }
.lab-thumb img { height: 54px; display: block; image-rendering: pixelated; }
.lab-thumb span { font-size: 11px; color: var(--ink-dim); }
.lab-thumb.active { border-color: var(--fox-gold-deep); }
.lab-canvas-scroll { overflow: auto; max-height: 62vh; border: 1px solid var(--paper-line); border-radius: 6px; background: #221c17; }
.lab-canvas { display: block; cursor: crosshair; image-rendering: pixelated; }
.lab-row-bottom { align-items: flex-start; justify-content: space-between; }
.lab-preview-box { display: grid; gap: 4px; justify-items: center; padding: 8px; background: var(--paper); border: 1px dashed var(--paper-line); border-radius: 8px; }
.lab-preview { display: block; max-width: 140px; max-height: 140px; image-rendering: pixelated; }
.lab-draft-preview { height: 40px; border: 1px solid var(--paper-line); border-radius: 4px; image-rendering: pixelated; }
.lab-sessions { display: flex; flex-wrap: wrap; gap: 8px 16px; margin: 0; padding: 8px 12px 10px; border: 1px solid var(--paper-line); border-radius: var(--r-sm); }
.lab-sessions legend { padding: 0 6px; font-size: 12px; color: var(--ink-dim); }
.lab-table-scroll { overflow-x: auto; }
.lab-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.lab-table th, .lab-table td { padding: 5px 8px; text-align: left; border-bottom: 1px solid var(--paper-line); font-variant-numeric: tabular-nums; }
.lab-table th { color: var(--ink-dim); font-weight: 700; }
.lab-score-hit { color: #426047; font-weight: 700; }
.lab-score-miss { color: #9f3d28; }
.lab-confusion { margin: 0; padding: 9px 12px 9px 26px; color: #9f3d28; background: color-mix(in srgb, #f4dfd7 68%, var(--paper-card)); border: 1px solid #d8a195; border-radius: 8px; font-size: 12px; }
.lab-verify { display: grid; gap: 8px; }

:global(body[data-theme='pixel']) .lab-card { color: #dce8e1; background: #252d33; border-color: #61727a; }
:global(body[data-theme='pixel']) .lab-hint { color: #aab8b1; }
:global(body[data-theme='pixel']) .lab-thumb,
:global(body[data-theme='pixel']) .lab-preview-box,
:global(body[data-theme='pixel']) .lab-zoom button { color: #dce8e1; background: #303940; border-color: #526169; }
:global(body[data-theme='pixel']) .lab-zoom button.active { color: #1a3055; background: #c9a227; }
:global(body[data-theme='pixel']) .lab-canvas-scroll { border-color: #46545c; }

@media (max-width: 860px) {
  .lab-row label :deep(.pixel-control) { width: 100%; }
  .lab-row label { flex: 1 1 140px; }
}
</style>
