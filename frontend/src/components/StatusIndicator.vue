<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  label: string
  status: 'online' | 'offline' | 'checking' | 'connected' | 'connecting' | 'disconnected'
}>()

const tone = computed(() => {
  if (props.status === 'online' || props.status === 'connected') return 'positive'
  if (props.status === 'checking' || props.status === 'connecting') return 'pending'
  return 'negative'
})
</script>

<template>
  <span class="status-indicator" :class="`status-${tone}`">
    <span class="status-dot" aria-hidden="true" />
    {{ label }}
  </span>
</template>
