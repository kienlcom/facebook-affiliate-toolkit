import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SessionStats from '../components/SessionStats.vue'

describe('SessionStats', () => {
  it('shows all required session counters and claim success rate', () => {
    const wrapper = mount(SessionStats, {
      props: {
        counters: {
          fetched: 8,
          opened: 7,
          confirmed: 6,
          claimed: 4,
          failed: 1,
          points_earned: 2400
        },
        elapsedSeconds: 125,
        remainingJobs: 12
      }
    })

    expect(wrapper.text()).toContain('Confirmed')
    expect(wrapper.text()).toContain('Failed')
    expect(wrapper.text()).toContain('80%')
    expect(wrapper.text()).toContain('02:05')
    expect(wrapper.text()).toContain('2.400')
  })
})
