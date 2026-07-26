<script setup lang="ts">
import { AlertTriangle, ArrowLeft, Download, LoaderCircle, Octagon, RefreshCw } from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { SessionSocket } from '../api/ws'
import type { SessionEvent, WarningType } from '../api/types'
import AutoOpenControls from '../components/AutoOpenControls.vue'
import JobPanel from '../components/JobPanel.vue'
import LogPanel from '../components/LogPanel.vue'
import NoJobsDialog from '../components/NoJobsDialog.vue'
import SessionStats from '../components/SessionStats.vue'
import StatusIndicator from '../components/StatusIndicator.vue'
import WarningDialog from '../components/WarningDialog.vue'
import { useAccountStore } from '../stores/account'
import { useJobsStore } from '../stores/jobs'
import { useLogsStore } from '../stores/logs'
import { useSessionStore } from '../stores/session'

const props = defineProps<{ id: string }>()
const router = useRouter()
const accountStore = useAccountStore()
const sessionStore = useSessionStore()
const jobsStore = useJobsStore()
const logsStore = useLogsStore()

const now = ref(Date.now())
const socketStatus = ref<'connecting' | 'connected' | 'disconnected'>('connecting')
const warningOpen = ref(false)
const noJobsOpen = ref(false)
const pageLoading = ref(true)
const summarySyncedAt = ref(Date.now())
let timer: number | null = null
let socket: SessionSocket | null = null

const profile = computed(() =>
  accountStore.profiles.find((item) => item.key === sessionStore.current?.profile_key)
)
const sessionRunning = computed(() => sessionStore.current?.status === 'RUNNING')
const autoOpenStatus = computed(() => sessionStore.summary?.auto_open ?? null)
const localBrowserMode = computed(
  () => autoOpenStatus.value?.mode === 'local_browser'
)
const autoOpenCountdown = computed(() => {
  const status = autoOpenStatus.value
  if (!status) return 0
  if (status.next_open_at) {
    return Math.max(
      0,
      Math.ceil((new Date(status.next_open_at).getTime() - now.value) / 1000)
    )
  }
  return status.seconds_remaining ?? 0
})
const fetchLocked = computed(() => sessionStore.isFetchLocked(props.id, now.value))
const fetchLockRemaining = computed(() => {
  const expiresAt = sessionStore.fetchLockUntil(props.id)
  if (expiresAt === null) return 0
  return Math.max(0, Math.ceil((expiresAt - now.value) / 1000))
})
const fetchDisabled = computed(
  () =>
    !sessionRunning.value ||
    jobsStore.busy ||
    jobsStore.hasActiveJobs ||
    fetchLocked.value ||
    pageLoading.value
)
const fetchTitle = computed(() => {
  if (fetchLocked.value) {
    return `Có thể lấy lại nhiệm vụ sau ${fetchLockRemaining.value} giây`
  }
  if (jobsStore.hasActiveJobs) return 'Xử lý hết batch hiện tại trước khi lấy thêm'
  return 'Lấy batch nhiệm vụ mới'
})
const countdown = computed(() => {
  const openedAt = jobsStore.current?.opened_at
  if (!openedAt) return 0
  const waitSeconds = profile.value?.minimum_claim_wait_seconds ?? 3
  return Math.max(0, Math.ceil((new Date(openedAt).getTime() + waitSeconds * 1000 - now.value) / 1000))
})
const elapsedSeconds = computed(() => {
  const summary = sessionStore.summary
  if (!summary) return 0
  if (!sessionRunning.value) return summary.elapsed_seconds
  return summary.elapsed_seconds + Math.max(0, Math.floor((now.value - summarySyncedAt.value) / 1000))
})
const error = computed(() => sessionStore.error ?? jobsStore.error)

onMounted(async () => {
  try {
    if (!accountStore.profiles.length) {
      await accountStore.loadDashboard()
    }
    await refresh()
    const shouldFetchInitialBatch = sessionStore.consumeInitialFetch(props.id)
    if (shouldFetchInitialBatch && sessionRunning.value && !jobsStore.hasActiveJobs) {
      await fetchJobs()
    }
    socket = new SessionSocket(
      props.id,
      handleEvent,
      (status) => {
        socketStatus.value = status
      },
      refresh
    )
    socket.connect()
    timer = window.setInterval(() => {
      now.value = Date.now()
    }, 250)
  } catch {
    return
  } finally {
    pageLoading.value = false
  }
})

onBeforeUnmount(() => {
  socket?.stop()
  if (timer !== null) window.clearInterval(timer)
})

async function refresh(): Promise<void> {
  const summary = await sessionStore.refresh(props.id)
  jobsStore.setJobs(summary.jobs)
  summarySyncedAt.value = Date.now()
}

async function fetchJobs(): Promise<void> {
  try {
    const fetchedCount = await jobsStore.fetch(props.id)
    await refresh()
    if (fetchedCount === 0) {
      sessionStore.lockFetch(props.id)
      noJobsOpen.value = true
    }
  } catch {
    return
  }
}

function openWindow(markOpened: boolean): void {
  if (localBrowserMode.value) return
  const job = jobsStore.current
  if (!job) return
  window.open(job.url, '_blank', 'noopener,noreferrer')
  if (markOpened) {
    void jobsStore.markOpened(job.id).then(refresh).catch(() => undefined)
  }
}

async function complete(): Promise<void> {
  const job = jobsStore.current
  if (!job) return
  try {
    await jobsStore.confirmAndClaim(job.id)
    await refresh()
  } catch {
    return
  }
}

async function skip(): Promise<void> {
  const job = jobsStore.current
  if (!job) return
  try {
    await jobsStore.skip(job.id)
    await refresh()
  } catch {
    return
  }
}

async function invalid(): Promise<void> {
  const job = jobsStore.current
  if (!job) return
  try {
    await jobsStore.markInvalid(job.id)
    await refresh()
  } catch {
    return
  }
}

async function stopSession(): Promise<void> {
  try {
    await sessionStore.stop(props.id)
  } catch {
    return
  }
}

async function stopAfterNoJobs(): Promise<void> {
  try {
    await sessionStore.stop(props.id)
    noJobsOpen.value = false
    await router.push('/')
  } catch {
    return
  }
}

function continueAfterNoJobs(): void {
  noJobsOpen.value = false
}

async function setAutoOpen(enabled: boolean): Promise<void> {
  try {
    await sessionStore.setAutoOpen(props.id, enabled)
  } catch {
    return
  }
}

async function pauseAutoOpen(): Promise<void> {
  try {
    await sessionStore.pauseAutoOpen(props.id)
  } catch {
    return
  }
}

async function resumeAutoOpen(): Promise<void> {
  try {
    await sessionStore.resumeAutoOpen(props.id)
  } catch {
    return
  }
}

async function submitWarning(type: WarningType, note: string | null): Promise<void> {
  try {
    await sessionStore.reportWarning(props.id, type, note)
    warningOpen.value = false
    await refresh()
  } catch {
    return
  }
}

function handleEvent(event: SessionEvent): void {
  logsStore.add(event)
  sessionStore.applyAutoOpenEvent(event)
  if (
    event.event.startsWith('job.') ||
    event.event.startsWith('session.') ||
    event.event === 'account.warning'
  ) {
    void refresh().catch(() => undefined)
  }
}
</script>

<template>
  <main class="page session-page">
    <div class="session-toolbar">
      <button class="icon-button" type="button" title="Về bảng điều khiển" @click="router.push('/')">
        <ArrowLeft :size="18" />
      </button>
      <div class="session-title">
        <p class="eyebrow">Session {{ id.slice(0, 8) }}</p>
        <h1>{{ profile?.display_name ?? 'Facebook Page' }}</h1>
      </div>
      <StatusIndicator
        :label="socketStatus === 'connected' ? 'Realtime connected' : socketStatus === 'connecting' ? 'Đang kết nối' : 'Realtime disconnected'"
        :status="socketStatus"
      />
      <div class="toolbar-actions">
        <button
          class="button button-secondary"
          type="button"
          :disabled="fetchDisabled"
          :title="fetchTitle"
          @click="fetchJobs"
        >
          <Download :size="17" /> Lấy nhiệm vụ
        </button>
        <button
          class="icon-button warning-icon"
          type="button"
          title="Báo cảnh báo tài khoản"
          :disabled="!sessionRunning"
          @click="warningOpen = true"
        >
          <AlertTriangle :size="18" />
        </button>
        <button
          class="icon-button danger-icon"
          type="button"
          title="Dừng phiên"
          :disabled="!sessionRunning || sessionStore.loading"
          @click="stopSession"
        >
          <Octagon :size="18" />
        </button>
      </div>
    </div>

    <div v-if="error" class="alert alert-error" role="alert">{{ error }}</div>
    <div v-if="fetchLocked && !noJobsOpen" class="alert alert-warning" role="status">
      Không có nhiệm vụ mới. Có thể thử lại sau {{ fetchLockRemaining }} giây.
    </div>
    <div
      v-if="jobsStore.claimResult"
      class="alert alert-success"
      data-testid="claim-notice"
      role="status"
      aria-live="polite"
    >
      <strong v-if="jobsStore.claimResult.points_added > 0">
        Đã claim thành công {{ jobsStore.claimResult.points_added.toLocaleString('vi-VN') }} xu.
      </strong>
      <strong v-else>{{ jobsStore.claimResult.message }}</strong>
      <span
        v-if="
          jobsStore.claimResult.points_added > 0 &&
          jobsStore.claimResult.balance_after !== null
        "
      >
        Số dư TDS: {{ jobsStore.claimResult.balance_after.toLocaleString('vi-VN') }} xu
      </span>
    </div>

    <div v-if="pageLoading || !sessionStore.summary" class="loading-view">
      <LoaderCircle class="spinning" :size="28" />
    </div>
    <template v-else>
      <AutoOpenControls
        v-if="autoOpenStatus"
        :status="autoOpenStatus"
        :countdown="autoOpenCountdown"
        :busy="sessionStore.loading"
        :session-running="sessionRunning"
        @toggle="setAutoOpen"
        @pause="pauseAutoOpen"
        @resume="resumeAutoOpen"
      />

      <SessionStats
        :counters="sessionStore.summary.counters"
        :elapsed-seconds="elapsedSeconds"
        :remaining-jobs="sessionStore.summary.remaining_jobs"
      />

      <div class="session-workspace">
        <aside class="panel queue-panel" aria-label="Danh sách nhiệm vụ">
          <div class="panel-heading compact-heading">
            <h2>Queue</h2>
            <button class="icon-button" type="button" title="Đồng bộ phiên" @click="refresh">
              <RefreshCw :size="16" />
            </button>
          </div>
          <button
            v-for="job in jobsStore.jobs"
            :key="job.id"
            class="queue-item"
            :class="{ selected: jobsStore.current?.id === job.id }"
            type="button"
            @click="jobsStore.selectedId = job.id"
          >
            <span>{{ job.action_label ?? 'Page' }}</span>
            <small>{{ job.state.replaceAll('_', ' ') }}</small>
          </button>
          <p v-if="!jobsStore.jobs.length" class="queue-empty">Queue trống</p>
        </aside>

        <JobPanel
          :job="jobsStore.current"
          :profile-label="profile?.display_name ?? 'Facebook Page'"
          :countdown="countdown"
          :busy="jobsStore.busy"
          :session-running="sessionRunning"
          :manual-link-opening="!localBrowserMode"
          @open="openWindow(true)"
          @reopen="openWindow(false)"
          @complete="complete"
          @skip="skip"
          @invalid="invalid"
        />

        <LogPanel
          v-model:filter="logsStore.filter"
          :events="logsStore.filteredEvents"
          @clear="logsStore.clear"
        />
      </div>
    </template>

    <WarningDialog
      :open="warningOpen"
      :busy="sessionStore.loading"
      @close="warningOpen = false"
      @submit="submitWarning"
    />
    <NoJobsDialog
      :open="noJobsOpen"
      :busy="sessionStore.loading"
      @stop="stopAfterNoJobs"
      @continue="continueAfterNoJobs"
    />
  </main>
</template>
