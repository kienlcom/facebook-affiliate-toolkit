<script setup lang="ts">
import { Clock3, Pause, Play, Power } from '@lucide/vue'
import { computed } from 'vue'

import type { AutoOpenStatus } from '../api/types'

const props = defineProps<{
  status: AutoOpenStatus
  countdown: number
  busy: boolean
  sessionRunning: boolean
}>()

defineEmits<{
  toggle: [enabled: boolean]
  pause: []
  resume: []
}>()

const stateLabel = computed(() => {
  if (!props.status.enabled) return 'Đang tắt'
  if (props.status.paused) return 'Tạm dừng'
  if (props.status.state === 'COUNTDOWN') return `Mở job kế sau ${props.countdown} giây`
  if (props.status.state === 'OPENING') return 'Đang mở trình duyệt'
  if (props.status.state === 'WAITING_USER') return 'Chờ bạn xử lý Facebook'
  if (props.status.reason === 'QUEUE_EMPTY') return 'Đã hết queue'
  return 'Đang chờ job'
})
</script>

<template>
  <section
    v-if="status.available"
    class="auto-open-bar"
    aria-label="Điều khiển tự động mở link"
  >
    <label class="auto-open-toggle">
      <input
        type="checkbox"
        :checked="status.enabled"
        :disabled="busy || !sessionRunning"
        @change="$emit('toggle', ($event.target as HTMLInputElement).checked)"
      />
      <span class="toggle-track" aria-hidden="true"><span /></span>
      <span>
        <strong>Tự động mở link</strong>
        <small>Local browser</small>
      </span>
    </label>

    <div class="auto-open-state" role="status" aria-live="polite">
      <Clock3 :size="16" />
      <span>{{ stateLabel }}</span>
    </div>

    <div class="auto-open-actions">
      <button
        v-if="status.enabled && !status.paused"
        class="icon-button"
        type="button"
        title="Tạm dừng tự động mở link"
        :disabled="busy || !sessionRunning"
        @click="$emit('pause')"
      >
        <Pause :size="17" />
      </button>
      <button
        v-if="status.enabled && status.paused"
        class="icon-button"
        type="button"
        title="Tiếp tục tự động mở link"
        :disabled="busy || !sessionRunning"
        @click="$emit('resume')"
      >
        <Play :size="17" fill="currentColor" />
      </button>
      <button
        v-if="status.enabled"
        class="icon-button danger-icon"
        type="button"
        title="Tắt tự động mở link"
        :disabled="busy"
        @click="$emit('toggle', false)"
      >
        <Power :size="17" />
      </button>
    </div>
  </section>
</template>
