import axios, { AxiosError } from 'axios'

import type {
  AccountProfile,
  ApiErrorEnvelope,
  ClaimResponse,
  FetchJobsResponse,
  HealthResponse,
  JobActionResponse,
  JobProfile,
  Session,
  SessionSummary,
  WarningType
} from './types'

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? ''

export const http = axios.create({
  baseURL: apiBaseUrl,
  timeout: 15_000,
  headers: {
    'Content-Type': 'application/json'
  }
})

export class FrontendApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly requestId?: string,
    public readonly details?: Record<string, unknown> | unknown[]
  ) {
    super(message)
  }
}

export function normalizeApiError(error: unknown): FrontendApiError {
  if (error instanceof FrontendApiError) {
    return error
  }
  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<ApiErrorEnvelope>
    const envelope = axiosError.response?.data?.error
    if (envelope) {
      return new FrontendApiError(
        envelope.code,
        envelope.message,
        envelope.request_id,
        envelope.details
      )
    }
    if (axiosError.code === 'ECONNABORTED') {
      return new FrontendApiError('REQUEST_TIMEOUT', 'Backend không phản hồi kịp thời')
    }
    return new FrontendApiError('BACKEND_UNAVAILABLE', 'Không thể kết nối backend')
  }
  return new FrontendApiError('UNKNOWN_ERROR', 'Đã xảy ra lỗi không xác định')
}

export const api = {
  async health(): Promise<HealthResponse> {
    return (await http.get<HealthResponse>('/health')).data
  },

  async accountProfile(): Promise<AccountProfile> {
    return (await http.get<AccountProfile>('/api/account/profile')).data
  },

  async profiles(): Promise<JobProfile[]> {
    return (await http.get<JobProfile[]>('/api/profiles')).data
  },

  async createSession(profileKey: string): Promise<Session> {
    return (await http.post<Session>('/api/sessions', { profile_key: profileKey })).data
  },

  async activeSession(): Promise<Session | null> {
    return (await http.get<Session | null>('/api/sessions/active')).data
  },

  async sessionSummary(sessionId: string): Promise<SessionSummary> {
    return (await http.get<SessionSummary>(`/api/sessions/${sessionId}/summary`)).data
  },

  async fetchJobs(sessionId: string): Promise<FetchJobsResponse> {
    return (await http.post<FetchJobsResponse>(`/api/sessions/${sessionId}/fetch`)).data
  },

  async stopSession(sessionId: string, reason = 'USER_REQUESTED'): Promise<Session> {
    return (await http.post<Session>(`/api/sessions/${sessionId}/stop`, { reason })).data
  },

  async accountWarning(
    sessionId: string,
    warningType: WarningType,
    note: string | null
  ): Promise<Session> {
    return (
      await http.post<Session>(`/api/sessions/${sessionId}/account-warning`, {
        warning_type: warningType,
        note
      })
    ).data
  },

  async markOpened(jobId: string): Promise<JobActionResponse> {
    return (await http.post<JobActionResponse>(`/api/jobs/${jobId}/opened`)).data
  },

  async confirm(jobId: string): Promise<JobActionResponse> {
    return (await http.post<JobActionResponse>(`/api/jobs/${jobId}/confirm`)).data
  },

  async claim(jobId: string): Promise<ClaimResponse> {
    return (await http.post<ClaimResponse>(`/api/jobs/${jobId}/claim`)).data
  },

  async skip(jobId: string, reason: string | null = null): Promise<JobActionResponse> {
    return (await http.post<JobActionResponse>(`/api/jobs/${jobId}/skip`, { reason })).data
  },

  async invalid(jobId: string): Promise<JobActionResponse> {
    return (await http.post<JobActionResponse>(`/api/jobs/${jobId}/invalid`)).data
  }
}
