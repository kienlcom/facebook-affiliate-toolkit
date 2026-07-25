import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useJobsStore } from '../stores/jobs'

const apiMock = vi.hoisted(() => ({
  fetchJobs: vi.fn(),
  confirm: vi.fn(),
  claim: vi.fn(),
  skip: vi.fn()
}))

vi.mock('../api/http', () => ({
  api: apiMock,
  normalizeApiError: (error: Error) => error
}))

const waitingJob = {
  id: 'job-id',
  session_id: 'session-id',
  external_id: '123',
  profile_key: 'facebook_page',
  url: 'https://www.facebook.com/123',
  action_label: 'page',
  state: 'WAITING_USER',
  fetched_at: '2026-07-25T12:00:00Z',
  opened_at: '2026-07-25T12:00:03Z',
  user_confirmed_at: null,
  claimed_at: null
}

describe('jobs store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMock.confirm.mockResolvedValue({
      job: { ...waitingJob, state: 'USER_CONFIRMED', user_confirmed_at: '2026-07-25T12:00:06Z' }
    })
    apiMock.claim.mockResolvedValue({
      job_id: 'job-id',
      status: 'CLAIMED',
      points_added: 0,
      balance_after: null,
      message: 'Job accepted',
      cache_count: 1,
      settlement_pending: true
    })
    apiMock.skip.mockResolvedValue({
      job: { ...waitingJob, state: 'USER_SKIPPED' }
    })
    apiMock.fetchJobs.mockResolvedValue({
      jobs: [{ ...waitingJob, id: 'fetched-job', state: 'VALIDATED' }],
      duplicates_ignored: 0
    })
  })

  it('fetches jobs for the active session', async () => {
    const store = useJobsStore()

    const count = await store.fetch('session-id')

    expect(apiMock.fetchJobs).toHaveBeenCalledWith('session-id')
    expect(count).toBe(1)
    expect(store.jobs[0].id).toBe('fetched-job')
    expect(store.hasActiveJobs).toBe(true)
  })

  it('confirms before claim', async () => {
    const store = useJobsStore()
    store.setJobs([{ ...waitingJob }])

    await store.confirmAndClaim('job-id')

    expect(apiMock.confirm).toHaveBeenCalledOnce()
    expect(apiMock.claim).toHaveBeenCalledOnce()
    expect(apiMock.confirm.mock.invocationCallOrder[0]).toBeLessThan(
      apiMock.claim.mock.invocationCallOrder[0]
    )
  })

  it('skip never calls claim', async () => {
    const store = useJobsStore()
    store.setJobs([{ ...waitingJob }])

    await store.skip('job-id')

    expect(apiMock.skip).toHaveBeenCalledOnce()
    expect(apiMock.claim).not.toHaveBeenCalled()
    expect(store.jobs[0].state).toBe('USER_SKIPPED')
  })
})
