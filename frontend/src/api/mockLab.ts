import axios, { AxiosError } from 'axios'

const configuredBaseUrl = (import.meta.env.VITE_MOCK_LAB_BASE_URL as string | undefined)?.replace(
  /\/$/,
  ''
)
const directBaseUrl = configuredBaseUrl ?? 'http://127.0.0.1:8090'
const apiBaseUrl = configuredBaseUrl ? `${directBaseUrl}/api` : '/mock-lab-api'
const healthUrl = configuredBaseUrl ? `${directBaseUrl}/health` : '/mock-lab-health'

const client = axios.create({
  timeout: 15_000,
  headers: {
    'Content-Type': 'application/json'
  }
})

export type MockLabStatus = 'online' | 'offline' | 'checking'

export interface MockLabHealth {
  status: string
  app_env: string
  circuit_state: string
}

export interface MockLabSession {
  id: string
  status: string
  stop_reason: string | null
  pause_reason: string | null
  seed_file: string
  jobs_fetched: number
  jobs_opened: number
  jobs_clicked: number
  jobs_action_verified: number
  jobs_claimed: number
  pending_points: number
  points_earned: number
  settlement_threshold: number
  settlement_wait_seconds: number
  settlement_pending_count: number
  settlement_eligible_at: string | null
  settled_at: string | null
  jobs?: Array<{
    id: string
    external_id: string
    state: string
  }>
}

export interface MockLabJob {
  id: string
  session_id: string
  external_id: string
  target_id: string
  action: string
  state: string
  points: number
  minimum_claim_wait_seconds: number
  opened_at: string | null
  claim_eligible_at: string | null
  action_verified_at: string | null
  verification_receipt_id: string | null
  claim_started_at: string | null
  claimed_at: string | null
  settled: boolean
  last_error_code: string | null
  url?: string
}

export interface MockLabJobUpdate {
  job_id: string
  state: string
  opened_at?: string | null
  claim_eligible_at?: string | null
  action_verified_at?: string | null
  verification_receipt_id?: string | null
  verification_receipt_trust?: string
}

export interface MockLabClaim {
  job_id: string
  state: string
  points_pending: number
  points_added: number
  settlement_pending_count: number
  settlement_required: boolean
  settlement_eligible_at: string | null
}

export interface MockLabSettlement {
  session_id: string
  settled_count: number
  points_settled: number
  pending_points: number
  points_earned: number
  settlement_pending_count: number
  settled_at: string
}

export interface MockLabFollowStatus {
  target_id: string
  following: boolean
  source: string
}

export interface MockLabRunnerEvent {
  ts: string
  level: 'INFO' | 'WARN' | 'ERROR'
  event: string
  data: Record<string, unknown>
  run_id?: string
  session_id?: string
  job_id?: string
  external_id?: string
}

export interface MockLabRunnerStatus {
  run_id: string
  seed_file: string
  base_url: string
  headed: boolean
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'STOPPED' | 'FAILED'
  started_at: string | null
  ended_at: string | null
  result: Record<string, unknown> | null
  error: string | null
  log_path: string
}

export interface MockLabRunnerLogs extends MockLabRunnerStatus {
  events: MockLabRunnerEvent[]
}

export interface MockLabErrorEnvelope {
  error?: {
    code?: string
    message?: string
    details?: Record<string, unknown>
  }
}

export class MockLabApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly details?: Record<string, unknown>
  ) {
    super(message)
  }
}

export function mockProfileUrl(pathOrUrl: string): string {
  if (/^https?:\/\//.test(pathOrUrl)) {
    return pathOrUrl
  }
  return `${directBaseUrl}${pathOrUrl.startsWith('/') ? pathOrUrl : `/${pathOrUrl}`}`
}

export function normalizeMockLabError(error: unknown): MockLabApiError {
  if (error instanceof MockLabApiError) return error
  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<MockLabErrorEnvelope>
    const envelope = axiosError.response?.data?.error
    if (envelope) {
      return new MockLabApiError(
        envelope.code ?? `HTTP_${axiosError.response?.status ?? 'ERROR'}`,
        envelope.message ?? envelope.code ?? 'Mock Lab request failed',
        envelope.details
      )
    }
    if (axiosError.code === 'ECONNABORTED') {
      return new MockLabApiError('REQUEST_TIMEOUT', 'Mock Lab did not respond in time')
    }
    return new MockLabApiError('MOCK_LAB_UNAVAILABLE', 'Cannot connect to Mock Lab')
  }
  return new MockLabApiError('UNKNOWN_ERROR', 'Unknown Mock Lab error')
}

export const mockLabApi = {
  async health(): Promise<MockLabHealth> {
    return (await client.get<MockLabHealth>(healthUrl)).data
  },

  async reset(): Promise<{ status: string }> {
    return (await client.post<{ status: string }>(`${apiBaseUrl}/reset`)).data
  },

  async createSession(seedFile: string): Promise<MockLabSession> {
    return (
      await client.post<MockLabSession>(`${apiBaseUrl}/sessions`, {
        seed_file: seedFile
      })
    ).data
  },

  async nextJob(sessionId: string): Promise<{ job: MockLabJob | null }> {
    return (
      await client.get<{ job: MockLabJob | null }>(`${apiBaseUrl}/jobs/next`, {
        params: { session_id: sessionId }
      })
    ).data
  },

  async markOpened(jobId: string): Promise<MockLabJobUpdate> {
    return (await client.post<MockLabJobUpdate>(`${apiBaseUrl}/jobs/${jobId}/opened`)).data
  },

  async followStatus(targetId: string): Promise<MockLabFollowStatus> {
    return (
      await client.get<MockLabFollowStatus>(`${apiBaseUrl}/mock-facebook/status`, {
        params: { target_id: targetId }
      })
    ).data
  },

  async verifyAction(jobId: string, targetId: string): Promise<MockLabJobUpdate> {
    return (
      await client.post<MockLabJobUpdate>(`${apiBaseUrl}/jobs/${jobId}/verify-action`, {
        target_id: targetId,
        verification_source: 'frontend_mock_lab'
      })
    ).data
  },

  async claim(jobId: string): Promise<MockLabClaim> {
    return (await client.post<MockLabClaim>(`${apiBaseUrl}/jobs/${jobId}/claim`)).data
  },

  async settle(sessionId: string): Promise<MockLabSettlement> {
    return (await client.post<MockLabSettlement>(`${apiBaseUrl}/claims/settle`, { session_id: sessionId }))
      .data
  },

  async stopSession(sessionId: string): Promise<MockLabSession> {
    return (
      await client.post<MockLabSession>(`${apiBaseUrl}/sessions/${sessionId}/stop`, {
        reason: 'USER_REQUESTED'
      })
    ).data
  },

  async summary(sessionId: string): Promise<MockLabSession> {
    return (await client.get<MockLabSession>(`${apiBaseUrl}/sessions/${sessionId}/summary`)).data
  },

  async startRunner(seedFile: string, headed = true): Promise<MockLabRunnerStatus> {
    return (
      await client.post<MockLabRunnerStatus>(`${apiBaseUrl}/runner/start`, {
        seed_file: seedFile,
        headed
      })
    ).data
  },

  async runnerStatus(runId: string): Promise<MockLabRunnerStatus> {
    return (
      await client.get<MockLabRunnerStatus>(`${apiBaseUrl}/runner/status`, {
        params: { run_id: runId }
      })
    ).data
  },

  async runnerLogs(runId: string): Promise<MockLabRunnerLogs> {
    return (
      await client.get<MockLabRunnerLogs>(`${apiBaseUrl}/runner/logs`, {
        params: { run_id: runId }
      })
    ).data
  }
}
