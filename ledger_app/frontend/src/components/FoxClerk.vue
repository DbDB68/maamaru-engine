<script setup lang="ts">
withDefaults(defineProps<{ action?: 'idle' | 'read' }>(), { action: 'idle' })
</script>

<template>
  <div class="fox-clerk" :class="`fox-${action}`" role="img" aria-label="账房狐之助"></div>
</template>

<style scoped>
/*
 * 两条 sprite 都是横向 6 帧条带：idle 单帧 298x880，read 单帧 362x724。
 * background-size 600% 让容器宽度正好等于一帧，再按百分比步进换帧。
 */
.fox-clerk {
  --fox-h: 148px;
  height: var(--fox-h);
  background-repeat: no-repeat;
  background-size: 600% 100%;
  image-rendering: pixelated;
  animation-timing-function: steps(1, end);
  animation-iteration-count: infinite;
  filter: drop-shadow(2px 3px 0 rgba(58, 43, 30, .28));
}
.fox-idle {
  width: calc(var(--fox-h) * 298 / 880);
  background-image: url('/static/img/fox_body_idle.png');
  animation-name: fox-idle-play, fox-breathe;
  animation-duration: 2.4s, 3.8s;
}
.fox-read {
  width: calc(var(--fox-h) * 362 / 724);
  background-image: url('/static/img/fox_read_scroll.png');
  animation-name: fox-read-play;
  animation-duration: 3.2s;
}
@keyframes fox-idle-play {
  0% { background-position-x: 0%; }
  16.7% { background-position-x: 20%; }
  33.4% { background-position-x: 40%; }
  50.1% { background-position-x: 60%; }
  66.8% { background-position-x: 80%; }
  83.5%, 100% { background-position-x: 100%; }
}
/* 卷轴完全摊开的那一帧多停一会儿，像真在核对账目。 */
@keyframes fox-read-play {
  0% { background-position-x: 0%; }
  10% { background-position-x: 20%; }
  20% { background-position-x: 40%; }
  30%, 66% { background-position-x: 60%; }
  78% { background-position-x: 80%; }
  88%, 100% { background-position-x: 100%; }
}
@keyframes fox-breathe {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-2px); }
}
@media (max-width: 720px) {
  .fox-clerk { --fox-h: 84px; }
}
@media (prefers-reduced-motion: reduce) {
  .fox-clerk { animation: none; background-position-x: 60%; }
}
</style>
