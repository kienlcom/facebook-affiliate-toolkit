import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { api, normalizeApiError } from '../api/http'
import type { ClaimResponse, Job } from '../api/types'

const activePriority = [
  'WAITING_USER',
  'USER_CONFIRMED',
  'CLAIM_PENDING',
  'CLAIMING',
  'RETRY_WAIT',
  'VALIDATED'
]
const activeStates = new Set([
  'FETCHED',
  'VALIDATED',
  'OPENING',
  'OPENED',
  'WAITING_USER',
  'USER_CONFIRMED',
  'CLAIM_PENDING',
  'CLAIMING',
  'RETRY_WAIT'
])

export const useJobsStore = defineStore('jobs', () => {
  const jobs = ref<Job[]>([])
  const selectedId = ref<string | null>(null)
  const claimResult = ref<ClaimResponse | null>(null)
  const busy = ref(false)
  const error = ref<string | null>(null)

  const current = computed(() => {
    const selected = jobs.value.find((job) => job.id === selectedId.value)
    if (selected && activePriority.includes(selected.state)) {
      return selected
    }
    for (const state of activePriority) {
      const match = jobs.value.find((job) => job.state === state)
      if (match) {
        return match
      }
    }
    return selected ?? jobs.value[0] ?? null
  })
  const hasActiveJobs = computed(() => jobs.value.some((job) => activeStates.has(job.state)))

  function setJobs(nextJobs: Job[]): void {
    jobs.value = nextJobs
    if (!selectedId.value || !nextJobs.some((job) => job.id === selectedId.value)) {
      selectedId.value = current.value?.id ?? nextJobs[0]?.id ?? null
    }
  }

  function updateJob(updated: Job): void {
    const index = jobs.value.findIndex((job) => job.id === updated.id)
    if (index >= 0) {
      jobs.value[index] = updated
    } else {
      jobs.value.push(updated)
    }
    selectedId.value = updated.id
  }

  async function fetch(sessionId: string): Promise<number> {
    return run(async () => {
      const result = await api.fetchJobs(sessionId)
      for (const job of result.jobs) {
        updateJob(job)
      }
      return result.jobs.length
    })
  }

  async function markOpened(jobId: string): Promise<void> {
    await run(async () => {
      updateJob((await api.markOpened(jobId)).job)
    })
  }

  async function confirmAndClaim(jobId: string): Promise<void> {
    await run(async () => {
      updateJob((await api.confirm(jobId)).job)
      claimResult.value = await api.claim(jobId)
    })
  }

  async function skip(jobId: string): Promise<void> {
    await run(async () => {
      updateJob((await api.skip(jobId)).job)
    })
  }

  async function markInvalid(jobId: string): Promise<void> {
    await run(async () => {
      updateJob((await api.invalid(jobId)).job)
    })
  }

  async function run<T>(operation: () => Promise<T>): Promise<T> {
    busy.value = true
    error.value = null
    try {
      return await operation()
    } catch (caught) {
      const normalized = normalizeApiError(caught)
      error.value = normalized.message
      throw normalized
    } finally {
      busy.value = false
    }
  }

  return {
    jobs,
    selectedId,
    current,
    hasActiveJobs,
    claimResult,
    busy,
    error,
    setJobs,
    fetch,
    markOpened,
    confirmAndClaim,
    skip,
    markInvalid
  }
})
