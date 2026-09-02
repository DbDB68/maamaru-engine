<script setup lang="ts">
import StyleLab from './components/StyleLab.vue'
</script>

<template>
  <main class="mobile-ledger">
    <StyleLab />
  </main>
</template>

<style>
html, body, #app { min-height: 100%; }
body { background: #ffd94d; overscroll-behavior-y: none; }
.mobile-ledger { min-height: 100vh; min-height: 100dvh; background: #ffd94d; }
.mobile-ledger .style-lab { width: 100%; min-height: 100vh; min-height: 100dvh; margin: 0; border-radius: 0; padding-top: max(24px, env(safe-area-inset-top)); padding-bottom: max(88px, calc(72px + env(safe-area-inset-bottom))); }
.mobile-ledger .lab-nav { bottom: max(10px, env(safe-area-inset-bottom)); }
</style>
