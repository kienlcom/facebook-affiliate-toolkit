import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type { SessionEvent, UiLogEvent } from '../api/types'

const MAX_EVENTS = 200
export type LogFilter = 'all' | 'job' | 'session' | 'api' | 'account'

export const useLogsStore = defineStore('logs', () => {
  const events = ref<UiLogEvent[]>([])
  const filter = ref<LogFilter>('all')
  const filteredEvents = computed(() => {
    if (filter.value === 'all') return events.value
    return events.value.filter((event) => event.event.startsWith(`${filter.value}.`))
  })

  function add(event: SessionEvent): void {
    events.value.unshift({
      ...event,
      id: `${event.timestamp}-${event.event}-${Math.random().toString(16).slice(2)}`
    })
    if (events.value.length > MAX_EVENTS) {
      events.value.length = MAX_EVENTS
    }
  }

  function clear(): void {
    events.value = []
  }

  return { events, filter, filteredEvents, add, clear }
})
