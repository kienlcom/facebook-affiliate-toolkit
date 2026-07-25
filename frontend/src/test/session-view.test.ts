import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAccountStore } from '../stores/account'
import SessionView from '../views/SessionView.vue'

const push = vi.fn()
const socketStop = vi.fn()
const apiMock = vi.hoisted(() => ({
  sessionSummary: vi.fn(),
  markOpened: vi.fn(),
  accountWarning: vi.fn(),
  fetchJobs: vi.fn(),
  stopSession: vi.fn()
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push })
}))

vi.mock('../api/ws', () => ({
  SessionSocket: class {
    connect(): void {}
    stop(): void {
      socketStop()
    }
  }
}))

vi.mock('../api/http', () => ({
  api: apiMock,
  normalizeApiError: (error: Error) => ({
    code: 'TEST_ERROR',
    message: error.message
  })
}))

describe('SessionView', () => {
  let summary: {
    session: Record<string, unknown>
    counters: Record<string, number>
    elapsed_seconds: number
    remaining_jobs: number
    jobs: Array<Record<string, unknown>>
  }

  beforeEach(() => {
    vi.clearAllMocks()
    const pinia = createPinia()
    setActivePinia(pinia)
    const accountStore = useAccountStore()
    accountStore.profiles = [
      {
        key: 'facebook_page',
        display_name: 'Facebook Page Follow',
        provider: 'tds',
        platform: 'facebook',
        minimum_claim_wait_seconds: 3,
        settlement_threshold: 5
      }
    ]
    summary = {
      session: {
        id: 'session-id',
        account_id: 'account-id',
        status: 'RUNNING',
        profile_key: 'facebook_page',
        started_at: '2026-07-25T12:00:00Z',
        ended_at: null,
        stop_reason: null,
        limits: { max_jobs: 20, max_duration_minutes: 30 }
      },
      counters: {
        fetched: 1,
        opened: 0,
        confirmed: 0,
        claimed: 0,
        failed: 0,
        points_earned: 0
      },
      elapsed_seconds: 10,
      remaining_jobs: 19,
      jobs: [
        {
          id: 'job-id',
          session_id: 'session-id',
          external_id: '123',
          profile_key: 'facebook_page',
          url: 'https://www.facebook.com/123',
          action_label: 'page',
          state: 'VALIDATED',
          fetched_at: '2026-07-25T12:00:00Z',
          opened_at: null,
          user_confirmed_at: null,
          claimed_at: null
        }
      ]
    }
    apiMock.sessionSummary.mockImplementation(async () => structuredClone(summary))
    apiMock.markOpened.mockImplementation(async () => {
      summary.jobs[0].state = 'WAITING_USER'
      summary.jobs[0].opened_at = new Date().toISOString()
      summary.counters.opened = 1
      return { job: structuredClone(summary.jobs[0]) }
    })
    apiMock.accountWarning.mockImplementation(async () => {
      summary.session.status = 'STOPPED'
      summary.session.stop_reason = 'ACCOUNT_WARNING:CHECKPOINT'
      return structuredClone(summary.session)
    })
  })

  it('opens Facebook with isolation flags and records the explicit open command', async () => {
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null)
    const pinia = createPinia()
    setActivePinia(pinia)
    useAccountStore().profiles = [
      {
        key: 'facebook_page',
        display_name: 'Facebook Page Follow',
        provider: 'tds',
        platform: 'facebook',
        minimum_claim_wait_seconds: 3,
        settlement_threshold: 5
      }
    ]
    const wrapper = mount(SessionView, {
      props: { id: 'session-id' },
      global: { plugins: [pinia] }
    })
    await flushPromises()

    await wrapper.get('.button-primary').trigger('click')
    await flushPromises()

    expect(openSpy).toHaveBeenCalledWith(
      'https://www.facebook.com/123',
      '_blank',
      'noopener,noreferrer'
    )
    expect(apiMock.markOpened).toHaveBeenCalledWith('job-id')
  })

  it('warning stops the session controls', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const accountStore = useAccountStore()
    accountStore.profiles = [
      {
        key: 'facebook_page',
        display_name: 'Facebook Page Follow',
        provider: 'tds',
        platform: 'facebook',
        minimum_claim_wait_seconds: 3,
        settlement_threshold: 5
      }
    ]
    const wrapper = mount(SessionView, {
      props: { id: 'session-id' },
      global: { plugins: [pinia] }
    })
    await flushPromises()

    await wrapper.get('.warning-icon').trigger('click')
    await wrapper.get('.dialog .button-danger').trigger('click')
    await flushPromises()

    expect(apiMock.accountWarning).toHaveBeenCalledWith('session-id', 'CHECKPOINT', null)
    const fetchButton = wrapper.findAll('button').find((button) => button.text().includes('Lấy nhiệm vụ'))
    expect(fetchButton?.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('Session')
  })
})
