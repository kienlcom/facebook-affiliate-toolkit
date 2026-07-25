<script setup lang="ts">
import {
  BadgeCheck,
  CheckCheck,
  Clock3,
  Coins,
  FolderDown,
  Gauge,
  MousePointerClick,
  Percent,
  XCircle
} from '@lucide/vue'

import type { SessionCounters } from '../api/types'

const props = defineProps<{
  counters: SessionCounters
  elapsedSeconds: number
  remainingJobs: number
}>()

function durationLabel(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return `${minutes.toString().padStart(2, '0')}:${rest.toString().padStart(2, '0')}`
}

function claimSuccessRate(): string {
  const attempts = props.counters.claimed + props.counters.failed
  if (attempts === 0) return '—'
  return `${Math.round((props.counters.claimed / attempts) * 100)}%`
}
</script>

<template>
  <section class="stats-band" aria-label="Thống kê phiên">
    <div><FolderDown :size="17" /><span><small>Fetched</small><strong>{{ counters.fetched }}</strong></span></div>
    <div><MousePointerClick :size="17" /><span><small>Opened</small><strong>{{ counters.opened }}</strong></span></div>
    <div><BadgeCheck :size="17" /><span><small>Confirmed</small><strong>{{ counters.confirmed }}</strong></span></div>
    <div><CheckCheck :size="17" /><span><small>Claimed</small><strong>{{ counters.claimed }}</strong></span></div>
    <div><XCircle :size="17" /><span><small>Failed</small><strong>{{ counters.failed }}</strong></span></div>
    <div><Coins :size="17" /><span><small>Xu</small><strong>{{ counters.points_earned.toLocaleString('vi-VN') }}</strong></span></div>
    <div><Percent :size="17" /><span><small>Claim rate</small><strong>{{ claimSuccessRate() }}</strong></span></div>
    <div><Gauge :size="17" /><span><small>Còn lại</small><strong>{{ remainingJobs }}</strong></span></div>
    <div><Clock3 :size="17" /><span><small>Thời gian</small><strong>{{ durationLabel(elapsedSeconds) }}</strong></span></div>
  </section>
</template>
