<script setup lang="ts">
import { AlertTriangle, ArrowLeft, Download, LoaderCircle, Octagon, RefreshCw } from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { SessionSocket } from '../api/ws'
import type { SessionEvent, WarningType } from '../api/types'
import JobPanel from '../components/JobPanel.vue'
import LogPanel from '../components/LogPanel.vue'
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
const pageLoading = ref(true)
const summarySyncedAt = ref(Date.now())
let timer: number | null = null
let socket: SessionSocket | null = null

const profile = computed(() =>
  accountStore.profiles.find((item) => item.key === sessionStore.current?.profile_key)
)
const sessionRunning = computed(() => sessionStore.current?.status === 'RUNNING')
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
    await jobsStore.fetch(props.id)
    await refresh()
  } catch {
    return
  }
}

function openWindow(markOpened: boolean): void {
  const job = jobsStore.current
  if (!job) return
  const openedWindow = window.open(job.url, '_blank', 'noopener,noreferrer')
  if (openedWindow && markOpened) {
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
          :disabled="!sessionRunning || jobsStore.busy || pageLoading"
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
    <div v-if="jobsStore.claimResult" class="alert alert-success" role="status">
      <strong>{{ jobsStore.claimResult.message }}</strong>
      <span v-if="jobsStore.claimResult.points_added">
        +{{ jobsStore.claimResult.points_added.toLocaleString('vi-VN') }} xu
      </span>
    </div>

    <div v-if="pageLoading || !sessionStore.summary" class="loading-view">
      <LoaderCircle class="spinning" :size="28" />
    </div>
    <template v-else>
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
  </main>
</template>
