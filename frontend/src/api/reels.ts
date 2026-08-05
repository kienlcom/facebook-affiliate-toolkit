import { http } from './http'

export interface ReelLink {
  id: string
  slug: string
  title: string
  url: string
  absolute_url: string
  image_count: number
  sort_order: number
  enabled: boolean
}

export type ReelRunStatus = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'STOPPED' | 'FAILED'

export interface ReelRunEvent {
  ts: string
  level: 'INFO' | 'WARN' | 'ERROR'
  event: string
  data: Record<string, unknown>
}

export interface ReelRun {
  run_id: string
  status: ReelRunStatus
  headed: boolean
  dwell_seconds: number
  link_count: number
  started_at: string | null
  ended_at: string | null
  result: {
    links_completed?: number
    links_failed?: number
    images_viewed?: number
    stopped?: boolean
  } | null
  error: string | null
}

export interface ReelRunLogs extends ReelRun {
  events: ReelRunEvent[]
}

export const reelsApi = {
  async links(): Promise<ReelLink[]> {
    return (await http.get<ReelLink[]>('/api/reels')).data
  },

  async startRun(dwellSeconds?: number): Promise<ReelRun> {
    return (
      await http.post<ReelRun>('/api/reels/run', {
        dwell_seconds: dwellSeconds ?? null
      })
    ).data
  },

  async runStatus(): Promise<ReelRunLogs> {
    return (await http.get<ReelRunLogs>('/api/reels/run')).data
  },

  async stopRun(): Promise<ReelRun> {
    return (await http.post<ReelRun>('/api/reels/run/stop')).data
  }
}
