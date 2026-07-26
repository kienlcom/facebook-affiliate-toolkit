import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it } from 'vitest'

import { useSessionStore } from '../stores/session'

describe('session store fetch lock', () => {
  it('persists a no-jobs lock across store recreation', () => {
    setActivePinia(createPinia())
    const firstStore = useSessionStore()
    firstStore.lockFetch('session-id')
    const expiresAt = firstStore.fetchLockUntil('session-id')
    expect(expiresAt).not.toBeNull()

    setActivePinia(createPinia())
    const recreatedStore = useSessionStore()
    expect(recreatedStore.isFetchLocked('session-id')).toBe(true)
    expect(recreatedStore.isFetchLocked('session-id', (expiresAt ?? 0) + 1)).toBe(false)
  })
})
