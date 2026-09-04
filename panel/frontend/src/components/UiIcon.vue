<script setup lang="ts">
defineProps<{ name: 'cards' | 'code' | 'eraser' | 'follow' | 'download' | 'external' }>()
const paths = {
  cards: 'M2 2h12v5H2zM2 10h5v4H2zM10 10h4v4h-4z',
  code: 'm5 4-4 4 4 4m6-8 4 4-4 4M9 2 7 14',
  eraser: 'm9 2 5 5-7 7H4l-3-3 8-9ZM5 7l5 5M7 14h8',
  follow: 'M2 3h6M2 7h4M2 11h4M11 2v10m-3-3 3 3 3-3M8 15h6',
  download: 'M8 1v9m-3-3 3 3 3-3M2 10v4h12v-4',
  external: 'M9 2h5v5M14 2 7 9M6 3H2v11h11v-4',
}
</script>

<template>
  <svg class="ui-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path :d="paths[name]" /></svg>
</template>

<style scoped>
.ui-icon { display: inline-block; width: 14px; height: 14px; flex: 0 0 14px; }
</style>
