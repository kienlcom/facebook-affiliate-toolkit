import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DashboardView from '../views/DashboardView.vue'

const push = vi.fn()
const apiMock = vi.hoisted(() => ({
  health: vi.fn(),
  accountProfile: vi.fn(),
  profiles: vi.fn(),
  createSession: vi.fn()
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
})
