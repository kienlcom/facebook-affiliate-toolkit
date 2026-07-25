import type { SessionEvent } from './types'

type EventHandler = (event: SessionEvent) => void
type StatusHandler = (status: 'connecting' | 'connected' | 'disconnected') => void
type WebSocketFactory = (url: string) => WebSocket

function websocketBaseUrl(): string {
  const configured = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '')
  if (configured) {
    return configured.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:')
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}`
}

export class SessionSocket {
  private socket: WebSocket | null = null
  private reconnectTimer: number | null = null
  private reconnectAttempt = 0
  private active = false
  private hasConnected = false

  constructor(
    private readonly sessionId: string,
    private readonly onEvent: EventHandler,
    private readonly onStatus: StatusHandler,
    private readonly onReconnect: () => void | Promise<void>,
    private readonly createSocket: WebSocketFactory = (url) => new WebSocket(url)
  ) {}

  connect(): void {
    this.active = true
    this.open()
  }

  stop(): void {
    this.active = false
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.socket?.close()
    this.socket = null
    this.onStatus('disconnected')
  }

  private open(): void {
    if (!this.active) {
      return
    }
    this.onStatus('connecting')
    const socket = this.createSocket(`${websocketBaseUrl()}/ws/sessions/${this.sessionId}`)
    this.socket = socket

    socket.onopen = () => {
      const isReconnect = this.hasConnected
      this.hasConnected = true
      this.reconnectAttempt = 0
      this.onStatus('connected')
      if (isReconnect) {
        void this.onReconnect()
      }
    }
    socket.onmessage = (message) => {
      try {
        this.onEvent(JSON.parse(String(message.data)) as SessionEvent)
      } catch (error: unknown) {
        const reason = error instanceof Error ? error.name : 'UnknownError'
        console.warn(`Malformed WebSocket event ignored (${reason})`)
      }
    }
    socket.onerror = () => {
      socket.close()
    }
    socket.onclose = () => {
      if (this.socket === socket) {
        this.socket = null
      }
      this.onStatus('disconnected')
      this.scheduleReconnect()
    }
  }

  private scheduleReconnect(): void {
    if (!this.active || this.reconnectTimer !== null) {
      return
    }
    const delays = [1000, 2000, 5000, 10_000]
    const delay = delays[Math.min(this.reconnectAttempt, delays.length - 1)]
    this.reconnectAttempt += 1
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.open()
    }, delay)
  }
}
