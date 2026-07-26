export interface ApiErrorEnvelope {
  error: {
    code: string
    message: string
    request_id: string
    details: Record<string, unknown> | unknown[]
  }
}

export interface HealthResponse {
  status: string
}

export interface AccountProfile {
  account_id: string
  display_name: string
  tds: {
    username: string | null
    balance: number | null
    status: string
  }
}

export interface JobProfile {
  key: string
  display_name: string
  provider: string
  platform: string
  minimum_claim_wait_seconds: number
  settlement_threshold: number
  verification_status?: 'GO' | 'PILOT'
}

export interface SessionLimits {
  max_jobs: number
  max_duration_minutes: number
}

export interface Session {
  id: string
  account_id: string
  status: string
  profile_key: string
  started_at: string
  ended_at: string | null
  stop_reason: string | null
  limits: SessionLimits
}

export interface SessionCounters {
  fetched: number
  opened: number
  confirmed: number
  claimed: number
  failed: number
  points_earned: number
}

export interface AutoOpenStatus {
  available: boolean
  mode: 'frontend_manual' | 'local_browser'
  enabled: boolean
  paused: boolean
  state: string
  interval_seconds: number
  next_open_at: string | null
  seconds_remaining: number | null
  reason: string | null
}

export interface Job {
  id: string
  session_id: string
  external_id: string
  profile_key: string
  url: string
  action_label: string | null
  state: string
  fetched_at: string
  opened_at: string | null
  user_confirmed_at: string | null
  claimed_at: string | null
}

export interface SessionSummary {
  session: Session
  counters: SessionCounters
  elapsed_seconds: number
  remaining_jobs: number
  jobs: Job[]
  auto_open: AutoOpenStatus
}

export interface FetchJobsResponse {
  jobs: Job[]
  duplicates_ignored: number
}

export interface JobActionResponse {
  job: Job
}

export interface ClaimResponse {
  job_id: string
  status: string
  points_added: number
  balance_after: number | null
  message: string
  cache_count: number | null
  settlement_pending: boolean
}

export type WarningType =
  | 'CHECKPOINT'
  | 'TEMPORARY_BLOCK'
  | 'IDENTITY_VERIFICATION'
  | 'FEATURE_UNAVAILABLE'
  | 'SUSPICIOUS_ACTIVITY'
  | 'OTHER'

export interface SessionEvent {
  event: string
  timestamp: string
  session_id: string
  data: Record<string, unknown>
}

export interface UiLogEvent extends SessionEvent {
  id: string
}
