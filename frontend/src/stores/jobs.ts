import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { api, normalizeApiError } from '../api/http'
import type { ClaimResponse, Job } from '../api/types'

const focusPriority = [
  'WAITING_USER',
  'USER_CONFIRMED',
  'CLAIM_PENDING',
  'CLAIMING',
  'RETRY_WAIT',
  'OPENING',
  'OPENED'
]
const activePriority = [
  ...focusPriority,
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
    const focused = firstByStatePriority(jobs.value, focusPriority)
    if (focused) {
      return focused
    }
    const selected = jobs.value.find((job) => job.id === selectedId.value)
    if (selected && activePriority.includes(selected.state)) {
      return selected
    }
    return firstByStatePriority(jobs.value, activePriority) ?? selected ?? jobs.value[0] ?? null
  })
  const hasActiveJobs = computed(() => jobs.value.some((job) => activeStates.has(job.state)))

  function setJobs(nextJobs: Job[]): void {
    jobs.value = nextJobs
    if (
      claimResult.value &&
      !nextJobs.some((job) => job.id === claimResult.value?.job_id)
    ) {
      claimResult.value = null
    }
    const focused = firstByStatePriority(nextJobs, focusPriority)
    if (focused) {
      selectedId.value = focused.id
    } else if (!selectedId.value || !nextJobs.some((job) => job.id === selectedId.value)) {
      selectedId.value = current.value?.id ?? nextJobs[0]?.id ?? null
    }
  }

  function updateJob(updated: Job, select = true): void {
    const index = jobs.value.findIndex((job) => job.id === updated.id)
    if (index >= 0) {
      jobs.value[index] = updated
    } else {
      jobs.value.push(updated)
    }
    if (select) {
      selectedId.value = updated.id
    }
  }

  function focusJob(jobId: string): void {
    if (jobs.value.some((job) => job.id === jobId)) {
      selectedId.value = jobId
    }
  }

  async function fetch(sessionId: string): Promise<number> {
    claimResult.value = null
    return run(async () => {
      const result = await api.fetchJobs(sessionId)
      for (const job of result.jobs) {
        updateJob(job, false)
      }
      if (
        result.jobs.length > 0 &&
        !jobs.value.some((job) => job.id === selectedId.value && activeStates.has(job.state))
      ) {
        selectedId.value = result.jobs[0].id
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
    claimResult.value = null
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
    focusJob,
    fetch,
    markOpened,
    confirmAndClaim,
    skip,
    markInvalid
  }
})

function firstByStatePriority(jobs: Job[], priorities: string[]): Job | undefined {
  for (const state of priorities) {
    const match = jobs.find((job) => job.state === state)
    if (match) return match
  }
  return undefined
}
