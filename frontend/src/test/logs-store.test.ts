import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useLogsStore } from '../stores/logs'

function event(name: string, index: number) {
  return {
    event: name,
    timestamp: `2026-07-25T12:00:${String(index % 60).padStart(2, '0')}Z`,
    session_id: 'session-id',
    data: {}
  }
}

describe('logs store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('filters event groups and caps retained history', () => {
    const store = useLogsStore()
    store.add(event('session.started', 0))
    store.add(event('job.opened', 1))
    store.filter = 'job'

    expect(store.filteredEvents).toHaveLength(1)
    expect(store.filteredEvents[0].event).toBe('job.opened')

    for (let index = 0; index < 205; index += 1) {
      store.add(event('api.called', index))
    }
    expect(store.events).toHaveLength(200)
  })
})
