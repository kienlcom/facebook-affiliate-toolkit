<script setup lang="ts">
import { CalendarClock, Fingerprint, Link2, Tag, ThumbsUp } from '@lucide/vue'

import type { Job } from '../api/types'
import ConfirmBar from './ConfirmBar.vue'

defineProps<{
  job: Job | null
  profileLabel: string
  countdown: number
  busy: boolean
  sessionRunning: boolean
  manualLinkOpening: boolean
}>()

defineEmits<{
  open: []
  reopen: []
  complete: []
  skip: []
  invalid: []
}>()

function formatTime(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('vi-VN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(new Date(value))
}
</script>

<template>
  <section class="panel job-panel" aria-labelledby="job-title">
    <div v-if="job" class="job-content">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">{{ profileLabel }}</p>
          <h2 id="job-title">{{ job.action_label ?? 'Facebook Page' }}</h2>
        </div>
        <span class="state-badge" :data-state="job.state">{{ job.state.replaceAll('_', ' ') }}</span>
      </div>

      <div class="job-id-line"><Fingerprint :size="15" /> {{ job.external_id }}</div>
      <div class="job-url"><Link2 :size="16" /><span>{{ job.url }}</span></div>

      <dl class="job-meta">
        <div><dt><Tag :size="15" /> Profile</dt><dd>{{ job.profile_key }}</dd></div>
        <div><dt><CalendarClock :size="15" /> Fetched</dt><dd>{{ formatTime(job.fetched_at) }}</dd></div>
        <div><dt><ThumbsUp :size="15" /> Opened</dt><dd>{{ formatTime(job.opened_at) }}</dd></div>
      </dl>

      <ConfirmBar
        :state="job.state"
        :countdown="countdown"
        :busy="busy"
        :session-running="sessionRunning"
        :manual-link-opening="manualLinkOpening"
        @open="$emit('open')"
        @reopen="$emit('reopen')"
        @complete="$emit('complete')"
        @skip="$emit('skip')"
        @invalid="$emit('invalid')"
      />
    </div>
    <div v-else class="empty-state">
      <ThumbsUp :size="28" aria-hidden="true" />
      <h2 id="job-title">Chưa có nhiệm vụ</h2>
      <p>Queue hiện đang trống.</p>
    </div>
  </section>
</template>
