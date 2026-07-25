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
        sessionRunning: true
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
})
