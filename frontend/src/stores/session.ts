import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api, normalizeApiError } from '../api/http'
import type { Session, SessionSummary, WarningType } from '../api/types'

export const useSessionStore = defineStore('session', () => {
  const current = ref<Session | null>(null)
  const summary = ref<SessionSummary | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

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

  return { current, summary, loading, error, start, refresh, stop, reportWarning }
})
