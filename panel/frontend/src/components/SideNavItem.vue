<script setup lang="ts">
defineProps<{ active?: boolean; running?: boolean }>()
defineEmits<{ click: [] }>()
</script>

<template>
  <button type="button" :class="{ active, running }" @click="$emit('click')">
    <slot />
  </button>
</template>
