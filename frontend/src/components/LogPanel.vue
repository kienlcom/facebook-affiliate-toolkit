<script setup lang="ts">
import { Radio, Trash2 } from '@lucide/vue'

import type { UiLogEvent } from '../api/types'
import type { LogFilter } from '../stores/logs'

defineProps<{
  events: UiLogEvent[]
  filter: LogFilter
}>()

defineEmits<{
  clear: []
  'update:filter': [value: LogFilter]
}>()

function eventTime(value: string): string {
  return new Intl.DateTimeFormat('vi-VN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(new Date(value))
}
</script>

<template>
  <section class="panel log-panel" aria-labelledby="log-title">
    <div class="panel-heading compact-heading">
      <h2 id="log-title"><Radio :size="17" /> Realtime</h2>
      <div class="log-tools">
        <select
          class="log-filter"
          aria-label="Lọc sự kiện"
          :value="filter"
          @change="$emit('update:filter', ($event.target as HTMLSelectElement).value as LogFilter)"
        >
          <option value="all">Tất cả</option>
          <option value="job">Job</option>
          <option value="session">Session</option>
          <option value="api">API</option>
          <option value="account">Account</option>
        </select>
        <button class="icon-button" type="button" title="Xóa log hiển thị" :disabled="events.length === 0" @click="$emit('clear')">
          <Trash2 :size="16" aria-hidden="true" />
        </button>
      </div>
    </div>
    <ol v-if="events.length" class="event-list">
      <li v-for="event in events" :key="event.id">
        <time>{{ eventTime(event.timestamp) }}</time>
        <span>{{ event.event }}</span>
      </li>
    </ol>
    <div v-else class="log-empty">
      {{ filter === 'all' ? 'Chưa có sự kiện.' : 'Không có sự kiện phù hợp.' }}
    </div>
  </section>
</template>
