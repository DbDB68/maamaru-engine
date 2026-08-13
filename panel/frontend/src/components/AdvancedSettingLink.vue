<script setup lang="ts">
defineProps<{ title: string; summary: string }>()
defineEmits<{ open: [] }>()
</script>

<template>
  <button type="button" class="advanced-setting-link" @click="$emit('open')">
    <span><b>{{ title }}</b><small>{{ summary }}</small></span><i>›</i>
  </button>
</template>
