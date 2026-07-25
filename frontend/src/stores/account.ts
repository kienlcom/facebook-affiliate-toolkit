import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api, normalizeApiError } from '../api/http'
import type { AccountProfile, JobProfile } from '../api/types'

export const useAccountStore = defineStore('account', () => {
  const account = ref<AccountProfile | null>(null)
  const profiles = ref<JobProfile[]>([])
  const backendStatus = ref<'checking' | 'online' | 'offline'>('checking')
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function loadDashboard(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const [health, loadedAccount, loadedProfiles] = await Promise.all([
        api.health(),
        api.accountProfile(),
        api.profiles()
      ])
      backendStatus.value = health.status === 'ok' ? 'online' : 'offline'
      account.value = loadedAccount
      profiles.value = loadedProfiles
    } catch (caught) {
      const normalized = normalizeApiError(caught)
      backendStatus.value = normalized.code === 'BACKEND_UNAVAILABLE' ? 'offline' : 'online'
      error.value = normalized.message
    } finally {
      loading.value = false
    }
  }

  return { account, profiles, backendStatus, loading, error, loadDashboard }
})
