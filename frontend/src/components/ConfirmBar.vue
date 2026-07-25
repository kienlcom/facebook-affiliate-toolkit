<script setup lang="ts">
import { Ban, Check, ExternalLink, RotateCcw, Unlink } from '@lucide/vue'

const props = defineProps<{
  state: string
  countdown: number
  busy: boolean
  sessionRunning: boolean
}>()

defineEmits<{
  open: []
  reopen: []
  complete: []
  skip: []
  invalid: []
}>()

function completeLabel(): string {
  return props.countdown > 0 ? `Chờ ${props.countdown}s` : 'Hoàn thành'
}
</script>

<template>
  <div class="confirm-bar">
    <button
      v-if="state === 'VALIDATED'"
      class="button button-primary"
      type="button"
      :disabled="busy || !sessionRunning"
      @click="$emit('open')"
    >
      <ExternalLink :size="17" /> Mở Facebook
    </button>
    <template v-else-if="state === 'WAITING_USER'">
      <button class="button button-secondary" type="button" :disabled="busy" @click="$emit('reopen')">
        <RotateCcw :size="17" /> Mở lại
      </button>
      <button
        class="button button-success"
        data-testid="complete-button"
        type="button"
        :disabled="busy || countdown > 0 || !sessionRunning"
        @click="$emit('complete')"
      >
        <Check :size="17" /> {{ completeLabel() }}
      </button>
      <button class="icon-button" type="button" title="Bỏ qua nhiệm vụ" :disabled="busy" @click="$emit('skip')">
        <Ban :size="18" aria-hidden="true" />
      </button>
      <button class="icon-button danger-icon" type="button" title="Báo link không hợp lệ" :disabled="busy" @click="$emit('invalid')">
        <Unlink :size="18" aria-hidden="true" />
      </button>
    </template>
    <span v-else class="state-note">{{ state.replaceAll('_', ' ') }}</span>
  </div>
</template>
