import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DashboardView from '../views/DashboardView.vue'

const push = vi.fn()
const apiMock = vi.hoisted(() => ({
  health: vi.fn(),
  accountProfile: vi.fn(),
  profiles: vi.fn(),
  activeSession: vi.fn(),
  createSession: vi.fn(),
  stopSession: vi.fn(),
  sessionSummary: vi.fn()
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push })
}))

vi.mock('../api/http', () => ({
  api: apiMock,
  normalizeApiError: (error: Error) => ({
    code: 'TEST_ERROR',
    message: error.message
  })
}))

describe('DashboardView', () => {
  beforeEach(() => {
    push.mockReset()
    apiMock.health.mockResolvedValue({ status: 'ok' })
    apiMock.accountProfile.mockResolvedValue({
      account_id: 'account-id',
      display_name: 'Local User',
      tds: { username: 'kienlcom', balance: 81300, status: 'VALID' }
    })
    apiMock.profiles.mockResolvedValue([
      {
        key: 'facebook_page',
        display_name: 'Facebook Page Follow',
        provider: 'tds',
        platform: 'facebook',
        minimum_claim_wait_seconds: 3,
        settlement_threshold: 5
      }
    ])
    apiMock.activeSession.mockResolvedValue(null)
    apiMock.createSession.mockResolvedValue({
      id: 'session-id',
      account_id: 'account-id',
      status: 'RUNNING',
      profile_key: 'facebook_page',
      started_at: '2026-07-25T12:00:00Z',
      ended_at: null,
      stop_reason: null,
      limits: { max_jobs: 20, max_duration_minutes: 30 }
    })
    apiMock.stopSession.mockResolvedValue({
      id: 'session-id',
      account_id: 'account-id',
      status: 'STOPPED',
      profile_key: 'facebook_page',
      started_at: '2026-07-25T12:00:00Z',
      ended_at: '2026-07-25T12:10:00Z',
      stop_reason: 'USER_REQUESTED',
      limits: { max_jobs: 20, max_duration_minutes: 30 }
    })
    apiMock.sessionSummary.mockResolvedValue({
      session: {
        id: 'session-id',
        account_id: 'account-id',
        status: 'STOPPED',
        profile_key: 'facebook_page',
        started_at: '2026-07-25T12:00:00Z',
        ended_at: '2026-07-25T12:10:00Z',
        stop_reason: 'USER_REQUESTED',
        limits: { max_jobs: 20, max_duration_minutes: 30 }
      },
      counters: {
        fetched: 0,
        opened: 0,
        confirmed: 0,
        claimed: 0,
        failed: 0,
        points_earned: 0
      },
      elapsed_seconds: 600,
      remaining_jobs: 20,
      jobs: []
    })
    apiMock.stopSession.mockClear()
  })

  it('loads dashboard data and starts a session', async () => {
    const wrapper = mount(DashboardView, {
      global: { plugins: [createPinia()] }
    })
    await flushPromises()

    expect(wrapper.text()).toContain('kienlcom')
    expect(wrapper.text()).toContain('81.300 xu')
    expect(wrapper.text()).toContain('Backend online')

    await wrapper.get('.start-button').trigger('click')
    await flushPromises()

    expect(apiMock.createSession).toHaveBeenCalledWith('facebook_page')
    expect(push).toHaveBeenCalledWith({
      name: 'session',
      params: { id: 'session-id' }
    })
  })

  it('starts the selected Facebook Follow pilot profile', async () => {
    apiMock.profiles.mockResolvedValue([
      {
        key: 'facebook_page',
        display_name: 'Facebook Page Follow',
        provider: 'tds',
        platform: 'facebook',
        minimum_claim_wait_seconds: 3,
        settlement_threshold: 5,
        verification_status: 'GO'
      },
      {
        key: 'facebook_follow',
        display_name: 'Facebook Follow',
        provider: 'tds',
        platform: 'facebook',
        minimum_claim_wait_seconds: 3,
        settlement_threshold: 5,
        verification_status: 'PILOT'
      }
    ])
    apiMock.createSession.mockResolvedValue({
      id: 'follow-session-id',
      account_id: 'account-id',
      status: 'RUNNING',
      profile_key: 'facebook_follow',
      started_at: '2026-07-26T12:00:00Z',
      ended_at: null,
      stop_reason: null,
      limits: { max_jobs: 20, max_duration_minutes: 30 }
    })

    const wrapper = mount(DashboardView, {
      global: { plugins: [createPinia()] }
    })
    await flushPromises()

    await wrapper.get('#profile-select').setValue('facebook_follow')
    expect(wrapper.text()).toContain('Facebook Follow')
    expect(wrapper.text()).toContain('Pilot')
    await wrapper.get('.start-button').trigger('click')
    await flushPromises()

    expect(apiMock.createSession).toHaveBeenCalledWith('facebook_follow')
  })

  it('resumes or stops the active session from the dashboard', async () => {
    apiMock.activeSession.mockResolvedValue({
      id: 'active-session-id',
      account_id: 'account-id',
      status: 'RUNNING',
      profile_key: 'facebook_page',
      started_at: '2026-07-25T12:00:00Z',
      ended_at: null,
      stop_reason: null,
      limits: { max_jobs: 20, max_duration_minutes: 30 }
    })
    apiMock.stopSession.mockResolvedValue({
      id: 'active-session-id',
      account_id: 'account-id',
      status: 'STOPPED',
      profile_key: 'facebook_page',
      started_at: '2026-07-25T12:00:00Z',
      ended_at: '2026-07-25T12:10:00Z',
      stop_reason: 'USER_REQUESTED',
      limits: { max_jobs: 20, max_duration_minutes: 30 }
    })
    apiMock.sessionSummary.mockResolvedValue({
      session: {
        id: 'active-session-id',
        account_id: 'account-id',
        status: 'STOPPED',
        profile_key: 'facebook_page',
        started_at: '2026-07-25T12:00:00Z',
        ended_at: '2026-07-25T12:10:00Z',
        stop_reason: 'USER_REQUESTED',
        limits: { max_jobs: 20, max_duration_minutes: 30 }
      },
      counters: {
        fetched: 5,
        opened: 5,
        confirmed: 5,
        claimed: 5,
        failed: 0,
        points_earned: 10500
      },
      elapsed_seconds: 600,
      remaining_jobs: 15,
      jobs: []
    })
    apiMock.stopSession.mockClear()

    const wrapper = mount(DashboardView, {
      global: { plugins: [createPinia()] }
    })
    await flushPromises()

    expect(wrapper.find('.start-button').exists()).toBe(false)
    await wrapper.get('.resume-button').trigger('click')
    expect(push).toHaveBeenCalledWith({
      name: 'session',
      params: { id: 'active-session-id' }
    })

    await wrapper.get('.dashboard-stop-button').trigger('click')
    await flushPromises()
    expect(apiMock.stopSession).toHaveBeenCalledWith('active-session-id')
    expect(wrapper.find('.start-button').exists()).toBe(true)
  })
})
