import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SessionSocket } from '../api/ws'

class FakeWebSocket {
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null

  close(): void {
    this.onclose?.()
  }
}

describe('SessionSocket', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('reconnects and requests a state resync', async () => {
    const instances: FakeWebSocket[] = []
    const onReconnect = vi.fn()
    const statuses: string[] = []
    const socket = new SessionSocket(
      'session-id',
      vi.fn(),
      (status) => statuses.push(status),
      onReconnect,
      () => {
        const instance = new FakeWebSocket()
        instances.push(instance)
        return instance as unknown as WebSocket
      }
    )

    socket.connect()
    instances[0].onopen?.()
    instances[0].onclose?.()
    await vi.advanceTimersByTimeAsync(1000)
    instances[1].onopen?.()

    expect(instances).toHaveLength(2)
    expect(onReconnect).toHaveBeenCalledOnce()
    expect(statuses).toContain('disconnected')
    expect(statuses[statuses.length - 1]).toBe('connected')
    socket.stop()
  })
})
