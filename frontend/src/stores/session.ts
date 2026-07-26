import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api, normalizeApiError } from '../api/http'
import type { Session, SessionSummary, WarningType } from '../api/types'

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
    try {
      current.value = await api.createSession(profileKey)
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

  return {
    current,
    summary,
    loading,
    error,
    fetchLockUntilBySession,
    lockFetch,
    unlockFetch,
    fetchLockUntil,
    isFetchLocked,
    loadActive,
    start,
    refresh,
    stop,
    reportWarning
  }
})
