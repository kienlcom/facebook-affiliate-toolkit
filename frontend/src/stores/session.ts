import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api, normalizeApiError } from '../api/http'
import type {
  AutoOpenStatus,
  Session,
  SessionEvent,
  SessionSummary,
  WarningType
} from '../api/types'

const FETCH_LOCK_STORAGE_KEY = 'tds_no_jobs_fetch_locks'
const NO_JOBS_COOLDOWN_SECONDS = 20

function readFetchLocks(): Record<string, number> {
  try {
    const stored = window.localStorage.getItem(FETCH_LOCK_STORAGE_KEY)
    if (!stored) return {}
    const parsed: unknown = JSON.parse(stored)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    return Object.fromEntries(
      Object.entries(parsed).filter(
        ([sessionId, expiresAt]) =>
          sessionId.length > 0 &&
          typeof expiresAt === 'number' &&
          Number.isFinite(expiresAt) &&
          expiresAt > Date.now()
      )
    )
  } catch {
    return {}
  }
}

export const useSessionStore = defineStore('session', () => {
  const current = ref<Session | null>(null)
  const summary = ref<SessionSummary | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const fetchLockUntilBySession = ref<Record<string, number>>(readFetchLocks())
  const pendingInitialFetchSessionId = ref<string | null>(null)

  function persistFetchLocks(): void {
    window.localStorage.setItem(
      FETCH_LOCK_STORAGE_KEY,
      JSON.stringify(fetchLockUntilBySession.value)
    )
  }

  function lockFetch(
    sessionId: string,
    cooldownSeconds = NO_JOBS_COOLDOWN_SECONDS
  ): void {
    fetchLockUntilBySession.value = {
      ...fetchLockUntilBySession.value,
      [sessionId]: Date.now() + cooldownSeconds * 1000
    }
    persistFetchLocks()
  }

  function unlockFetch(sessionId: string): void {
    const nextLocks = { ...fetchLockUntilBySession.value }
    delete nextLocks[sessionId]
    fetchLockUntilBySession.value = nextLocks
    persistFetchLocks()
  }

  function fetchLockUntil(sessionId: string): number | null {
    return fetchLockUntilBySession.value[sessionId] ?? null
  }

  function isFetchLocked(sessionId: string, at = Date.now()): boolean {
    const expiresAt = fetchLockUntil(sessionId)
    return expiresAt !== null && expiresAt > at
  }

  function consumeInitialFetch(sessionId: string): boolean {
    if (pendingInitialFetchSessionId.value !== sessionId) return false
    pendingInitialFetchSessionId.value = null
    return true
  }

  async function loadActive(): Promise<Session | null> {
    loading.value = true
    error.value = null
    try {
      current.value = await api.activeSession()
      if (current.value === null) {
        fetchLockUntilBySession.value = {}
        persistFetchLocks()
      }
      return current.value
    } catch (caught) {
      const normalized = normalizeApiError(caught)
      error.value = normalized.message
      throw normalized
    } finally {
      loading.value = false
    }
  }

  async function start(profileKey: string): Promise<Session> {
    loading.value = true
    error.value = null
    pendingInitialFetchSessionId.value = null
    try {
      current.value = await api.createSession(profileKey)
      pendingInitialFetchSessionId.value = current.value.id
      return current.value
    } catch (caught) {
      const normalized = normalizeApiError(caught)
      error.value = normalized.message
      throw normalized
    } finally {
      loading.value = false
    }
  }

  async function refresh(sessionId: string): Promise<SessionSummary> {
    try {
      summary.value = await api.sessionSummary(sessionId)
      current.value = summary.value.session
      return summary.value
    } catch (caught) {
      const normalized = normalizeApiError(caught)
      error.value = normalized.message
      throw normalized
    }
  }

  async function stop(sessionId: string): Promise<void> {
    loading.value = true
    error.value = null
    try {
      current.value = await api.stopSession(sessionId)
      await refresh(sessionId)
      unlockFetch(sessionId)
      if (pendingInitialFetchSessionId.value === sessionId) {
        pendingInitialFetchSessionId.value = null
      }
    } catch (caught) {
      const normalized = normalizeApiError(caught)
      error.value = normalized.message
      throw normalized
    } finally {
      loading.value = false
    }
  }

  async function reportWarning(
    sessionId: string,
    warningType: WarningType,
    note: string | null
  ): Promise<void> {
    loading.value = true
    error.value = null
    try {
      current.value = await api.accountWarning(sessionId, warningType, note)
      await refresh(sessionId)
    } catch (caught) {
      const normalized = normalizeApiError(caught)
      error.value = normalized.message
      throw normalized
    } finally {
      loading.value = false
    }
  }

  async function setAutoOpen(sessionId: string, enabled: boolean): Promise<void> {
    await updateAutoOpen(() => api.setAutoOpen(sessionId, enabled))
  }

  async function pauseAutoOpen(sessionId: string): Promise<void> {
    await updateAutoOpen(() => api.pauseAutoOpen(sessionId))
  }

  async function resumeAutoOpen(sessionId: string): Promise<void> {
    await updateAutoOpen(() => api.resumeAutoOpen(sessionId))
  }

  function applyAutoOpenEvent(event: SessionEvent): void {
    if (!summary.value || event.session_id !== summary.value.session.id) return
    const status = summary.value.auto_open
    if (event.event === 'auto_open.next_in') {
      const seconds = event.data.seconds_remaining
      const nextOpenAt = event.data.next_open_at
      if (typeof seconds === 'number') status.seconds_remaining = seconds
      if (typeof nextOpenAt === 'string') status.next_open_at = nextOpenAt
      status.state = 'COUNTDOWN'
      return
    }
    if (event.event === 'job.auto_opened') {
      status.state = 'WAITING_USER'
      status.next_open_at = null
      status.seconds_remaining = null
      status.reason = 'WAITING_FOR_USER'
      return
    }
    if (event.event === 'session.auto_open_paused') {
      status.paused = true
      status.state = 'PAUSED'
      status.next_open_at = null
      status.seconds_remaining = null
      status.reason =
        typeof event.data.reason === 'string' ? event.data.reason : 'USER_PAUSED'
      return
    }
    if (event.event === 'session.auto_open_resumed') {
      status.paused = false
      status.state = 'IDLE'
      status.reason = null
      return
    }
    if (event.event === 'session.auto_open_enabled') {
      status.enabled = event.data.enabled === true
      status.paused = event.data.paused === true
      status.state = status.enabled ? 'IDLE' : 'OFF'
      status.reason = null
    }
  }

  async function updateAutoOpen(
    operation: () => Promise<AutoOpenStatus>
  ): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const status = await operation()
      if (summary.value) summary.value.auto_open = status
    } catch (caught) {
      const normalized = normalizeApiError(caught)
      error.value = normalized.message
      throw normalized
    } finally {
      loading.value = false
    }
  }

  return {
    current,
    summary,
    loading,
    error,
    fetchLockUntilBySession,
    pendingInitialFetchSessionId,
    lockFetch,
    unlockFetch,
    fetchLockUntil,
    isFetchLocked,
    consumeInitialFetch,
    loadActive,
    start,
    refresh,
    stop,
    reportWarning,
    setAutoOpen,
    pauseAutoOpen,
    resumeAutoOpen,
    applyAutoOpenEvent
  }
})
