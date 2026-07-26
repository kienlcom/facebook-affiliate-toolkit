import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ConfirmBar from '../components/ConfirmBar.vue'

describe('ConfirmBar', () => {
  it('keeps manual completion disabled until countdown ends', async () => {
    const wrapper = mount(ConfirmBar, {
      props: {
        state: 'WAITING_USER',
        countdown: 2,
        busy: false,
        sessionRunning: true,
        manualLinkOpening: true
      }
    })
    const button = wrapper.get('[data-testid="complete-button"]')
    expect(button.attributes('disabled')).toBeDefined()
    expect(button.text()).toContain('Chờ 2s')

    await wrapper.setProps({ countdown: 0 })
    expect(button.attributes('disabled')).toBeUndefined()
    await button.trigger('click')
    expect(wrapper.emitted('complete')).toHaveLength(1)
  })

  it('does not expose frontend link opening controls in local browser mode', () => {
    const validated = mount(ConfirmBar, {
      props: {
        state: 'VALIDATED',
        countdown: 0,
        busy: false,
        sessionRunning: true,
        manualLinkOpening: false
      }
    })
    const waiting = mount(ConfirmBar, {
      props: {
        state: 'WAITING_USER',
        countdown: 0,
        busy: false,
        sessionRunning: true,
        manualLinkOpening: false
      }
    })

    expect(validated.text()).toContain('Chờ backend mở link')
    expect(validated.find('button').exists()).toBe(false)
    expect(waiting.text()).not.toContain('Mở lại')
    expect(waiting.get('[data-testid="complete-button"]').text()).toContain('Hoàn thành')
  })
})
