<script setup lang="ts">
import {
  BadgeCheck,
  Coins,
  ExternalLink,
  LoaderCircle,
  Octagon,
  Play,
  RefreshCw,
  RotateCcw,
  SearchCheck,
  Server
} from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  mockLabApi,
  mockProfileUrl,
  normalizeMockLabError,
  type MockLabClaim,
  type MockLabFollowStatus,
  type MockLabHealth,
  type MockLabJob,
  type MockLabRunnerEvent,
  type MockLabRunnerStatus,
  type MockLabSession,
  type MockLabSettlement,
  type MockLabStatus
} from '../api/mockLab'
import StatusIndicator from '../components/StatusIndicator.vue'

const seedOptions = [
  { value: 'jobs_single.json', label: 'Single success' },
  { value: 'jobs_happy.json', label: 'Happy batch' },
  { value: 'jobs_min_wait.json', label: 'Minimum wait' },
  { value: 'jobs_fault_no_button.json', label: 'No button' },
  { value: 'jobs_fault_captcha.json', label: 'CAPTCHA' },
  { value: 'jobs_fault_checkpoint.json', label: 'Checkpoint' },
  { value: 'jobs_fault_slow_ok.json', label: 'Slow render ok' },
  { value: 'jobs_fault_slow_timeout.json', label: 'Slow render timeout' }
]

const status = ref<MockLabStatus>('checking')
const health = ref<MockLabHealth | null>(null)
const session = ref<MockLabSession | null>(null)
const currentJob = ref<MockLabJob | null>(null)
const selectedSeed = ref(seedOptions[0].value)
const followStatus = ref<MockLabFollowStatus | null>(null)
const claimResult = ref<MockLabClaim | null>(null)
const settlementResult = ref<MockLabSettlement | null>(null)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const busyAction = ref<string | null>(null)
const events = ref<string[]>([])
const runnerStatus = ref<MockLabRunnerStatus | null>(null)
const runnerEvents = ref<MockLabRunnerEvent[]>([])
let runnerPollTimer: number | null = null

const canUseSession = computed(() => Boolean(session.value?.id) && session.value?.status === 'RUNNING')
const canOpenJob = computed(() => Boolean(currentJob.value?.url))
const canVerify = computed(() => Boolean(currentJob.value?.id && followStatus.value?.following))
const canClaim = computed(() => currentJob.value?.state === 'ACTION_VERIFIED')
const canSettle = computed(() => {
  const activeSession = session.value
  return Boolean(
    activeSession &&
      activeSession.settlement_pending_count >= activeSession.settlement_threshold
  )
})

onMounted(() => {
  void checkHealth()
})

onBeforeUnmount(() => {
  stopRunnerPolling()
})

async function runAction(label: string, action: () => Promise<void>): Promise<void> {
  busyAction.value = label
  error.value = null
  notice.value = null
  try {
    await action()
  } catch (caught) {
    const normalized = normalizeMockLabError(caught)
    error.value = `${normalized.code}: ${normalized.message}`
    addEvent(`error ${normalized.code}`)
  } finally {
    busyAction.value = null
  }
}

function addEvent(message: string): void {
  const stamp = new Date().toLocaleTimeString('vi-VN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
  events.value = [`${stamp} ${message}`, ...events.value].slice(0, 12)
}

function formatRunnerEvent(event: MockLabRunnerEvent): string {
  const externalId = event.external_id ? ` ${event.external_id}` : ''
  const status = event.level === 'ERROR' ? 'error ' : ''
  return `${status}${event.event}${externalId}`
}

async function checkHealth(): Promise<void> {
  status.value = 'checking'
  busyAction.value = 'health'
  error.value = null
  notice.value = null
  try {
    health.value = await mockLabApi.health()
    status.value = 'online'
    addEvent(`health ${health.value.status} (${health.value.circuit_state})`)
  } catch (caught) {
    const normalized = normalizeMockLabError(caught)
    status.value = 'offline'
    error.value = `${normalized.code}: ${normalized.message}`
    addEvent(`error ${normalized.code}`)
  } finally {
    busyAction.value = null
  }
}

async function resetLab(): Promise<void> {
  await runAction('reset', async () => {
    await mockLabApi.reset()
    session.value = null
    currentJob.value = null
    followStatus.value = null
    claimResult.value = null
    settlementResult.value = null
    notice.value = 'Mock Lab reset'
    addEvent('lab reset')
    await checkHealth()
  })
}

async function createSession(): Promise<void> {
  await runAction('create session', async () => {
    session.value = await mockLabApi.createSession(selectedSeed.value)
    currentJob.value = null
    followStatus.value = null
    claimResult.value = null
    settlementResult.value = null
    notice.value = `Session ${session.value.id.slice(0, 8)} created`
    addEvent(`session started ${selectedSeed.value}`)
  })
}

async function startSeleniumRunner(): Promise<void> {
  await runAction('run selenium', async () => {
    stopRunnerPolling()
    runnerEvents.value = []
    runnerStatus.value = await mockLabApi.startRunner(selectedSeed.value, true)
    notice.value = `Runner ${runnerStatus.value.run_id.slice(0, 8)} started`
    addEvent(`selenium runner started ${selectedSeed.value}`)
    startRunnerPolling(runnerStatus.value.run_id)
  })
}

function startRunnerPolling(runId: string): void {
  stopRunnerPolling()
  void pollRunner(runId)
  runnerPollTimer = window.setInterval(() => {
    void pollRunner(runId)
  }, 700)
}

function stopRunnerPolling(): void {
  if (runnerPollTimer !== null) {
    window.clearInterval(runnerPollTimer)
    runnerPollTimer = null
  }
}

async function pollRunner(runId: string): Promise<void> {
  try {
    const logs = await mockLabApi.runnerLogs(runId)
    runnerStatus.value = logs
    runnerEvents.value = logs.events
    if (!['PENDING', 'RUNNING'].includes(logs.status)) {
      stopRunnerPolling()
      const summary = logs.result?.summary as MockLabSession | undefined
      if (summary) {
        session.value = summary
      }
      notice.value = `Runner ${logs.status.toLowerCase()}`
      addEvent(`selenium runner ${logs.status.toLowerCase()}`)
    }
  } catch (caught) {
    stopRunnerPolling()
    const normalized = normalizeMockLabError(caught)
    error.value = `${normalized.code}: ${normalized.message}`
    addEvent(`runner error ${normalized.code}`)
  }
}

async function refreshSummary(): Promise<void> {
  const activeSession = session.value
  if (!activeSession) return
  session.value = await mockLabApi.summary(activeSession.id)
}

async function loadNextJob(): Promise<void> {
  const activeSession = session.value
  if (!activeSession) return
  await runAction('next job', async () => {
    const response = await mockLabApi.nextJob(activeSession.id)
    currentJob.value = response.job
    followStatus.value = null
    claimResult.value = null
    settlementResult.value = null
    if (response.job) {
      notice.value = `Loaded ${response.job.external_id}`
      addEvent(`job loaded ${response.job.external_id}`)
    } else {
      notice.value = 'No more jobs'
      addEvent('queue empty')
    }
    await refreshSummary()
  })
}

async function openProfile(): Promise<void> {
  const job = currentJob.value
  if (!job?.url) return
  const url = job.url
  await runAction('open profile', async () => {
    window.open(mockProfileUrl(url), '_blank', 'noopener,noreferrer')
    const opened = await mockLabApi.markOpened(job.id)
    currentJob.value = {
      ...job,
      state: opened.state,
      opened_at: opened.opened_at ?? job.opened_at,
      claim_eligible_at: opened.claim_eligible_at ?? job.claim_eligible_at
    }
    notice.value = 'Profile opened'
    addEvent(`profile opened ${job.target_id}`)
    await refreshSummary()
  })
}

async function checkFollowStatus(): Promise<void> {
  const job = currentJob.value
  if (!job) return
  await runAction('follow status', async () => {
    followStatus.value = await mockLabApi.followStatus(job.target_id)
    notice.value = followStatus.value.following ? 'Follow detected' : 'Follow not detected'
    addEvent(`follow ${followStatus.value.following ? 'true' : 'false'} ${job.target_id}`)
    await refreshSummary()
  })
}

async function verifyAction(): Promise<void> {
  const job = currentJob.value
  if (!job) return
  await runAction('verify', async () => {
    const verified = await mockLabApi.verifyAction(job.id, job.target_id)
    currentJob.value = {
      ...job,
      state: verified.state,
      action_verified_at: verified.action_verified_at ?? job.action_verified_at,
      verification_receipt_id:
        verified.verification_receipt_id ?? job.verification_receipt_id,
      claim_eligible_at: verified.claim_eligible_at ?? job.claim_eligible_at
    }
    notice.value = 'Action verified'
    addEvent(`verified ${job.external_id}`)
    await refreshSummary()
  })
}

async function claimJob(): Promise<void> {
  const job = currentJob.value
  if (!job) return
  await runAction('claim', async () => {
    claimResult.value = await mockLabApi.claim(job.id)
    currentJob.value = {
      ...job,
      state: claimResult.value.state,
      claimed_at: new Date().toISOString()
    }
    notice.value = `Claim pending ${claimResult.value.points_pending} points`
    addEvent(`claimed ${job.external_id}`)
    await refreshSummary()
  })
}

async function settleSession(): Promise<void> {
  const activeSession = session.value
  if (!activeSession) return
  await runAction('settle', async () => {
    settlementResult.value = await mockLabApi.settle(activeSession.id)
    notice.value = `Settled ${settlementResult.value.points_settled} points`
    addEvent(`settled ${settlementResult.value.settled_count} jobs`)
    await refreshSummary()
  })
}

async function stopSession(): Promise<void> {
  const activeSession = session.value
  if (!activeSession) return
  await runAction('stop', async () => {
    session.value = await mockLabApi.stopSession(activeSession.id)
    notice.value = 'Session stopped'
    addEvent('session stopped')
  })
}
</script>

<template>
  <main class="page mock-lab-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">Local automation lab</p>
        <h1>Mock Lab</h1>
      </div>
      <div class="health-cluster">
        <StatusIndicator
          :label="status === 'online' ? 'Mock Lab online' : status === 'checking' ? 'Checking Mock Lab' : 'Mock Lab offline'"
          :status="status"
        />
        <button class="icon-button" type="button" title="Refresh Mock Lab" @click="checkHealth">
          <RefreshCw :size="16" />
        </button>
      </div>
    </div>

    <div v-if="error" class="alert alert-error" role="alert">{{ error }}</div>
    <div v-if="notice" class="alert alert-success" role="status">{{ notice }}</div>

    <div class="mock-lab-layout">
      <section class="panel lab-control-panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">Scenario</p>
            <h2>{{ selectedSeed }}</h2>
          </div>
          <Server :size="20" aria-hidden="true" />
        </div>

        <label class="field-label">
          <span>Seed file</span>
          <select v-model="selectedSeed" :disabled="Boolean(busyAction)">
            <option v-for="seed in seedOptions" :key="seed.value" :value="seed.value">
              {{ seed.label }}
            </option>
          </select>
        </label>

        <div class="lab-actions">
          <button class="button button-secondary" type="button" :disabled="Boolean(busyAction)" @click="resetLab">
            <RotateCcw :size="17" /> Reset
          </button>
          <button class="button button-primary" type="button" :disabled="Boolean(busyAction)" @click="createSession">
            <Play :size="17" fill="currentColor" /> Start manual
          </button>
          <button
            class="button button-success"
            type="button"
            :disabled="Boolean(busyAction) || runnerStatus?.status === 'RUNNING'"
            @click="startSeleniumRunner"
          >
            <Play :size="17" fill="currentColor" /> Run Selenium
          </button>
        </div>

        <dl class="lab-meta">
          <div>
            <dt>Server</dt>
            <dd>{{ health?.app_env ?? 'unknown' }}</dd>
          </div>
          <div>
            <dt>Circuit</dt>
            <dd>{{ health?.circuit_state ?? 'unknown' }}</dd>
          </div>
          <div>
            <dt>Session</dt>
            <dd>{{ session ? session.id.slice(0, 8) : 'none' }}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{{ session?.status ?? 'idle' }}</dd>
          </div>
          <div>
            <dt>Runner</dt>
            <dd>{{ runnerStatus?.status ?? 'idle' }}</dd>
          </div>
          <div>
            <dt>Run ID</dt>
            <dd>{{ runnerStatus ? runnerStatus.run_id.slice(0, 8) : 'none' }}</dd>
          </div>
        </dl>
      </section>

      <section class="panel lab-work-panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">Workflow</p>
            <h2>{{ currentJob?.external_id ?? 'No active job' }}</h2>
          </div>
          <span v-if="currentJob" class="state-badge" :data-state="currentJob.state">
            {{ currentJob.state.replaceAll('_', ' ') }}
          </span>
        </div>

        <div class="lab-step-grid">
          <button class="button button-secondary" type="button" :disabled="!canUseSession || Boolean(busyAction)" @click="loadNextJob">
            <SearchCheck :size="17" /> Next job
          </button>
          <button class="button button-primary" type="button" :disabled="!canOpenJob || Boolean(busyAction)" @click="openProfile">
            <ExternalLink :size="17" /> Open profile
          </button>
          <button class="button button-secondary" type="button" :disabled="!currentJob || Boolean(busyAction)" @click="checkFollowStatus">
            <RefreshCw :size="17" /> Follow status
          </button>
          <button class="button button-success" type="button" :disabled="!canVerify || Boolean(busyAction)" @click="verifyAction">
            <BadgeCheck :size="17" /> Verify
          </button>
          <button class="button button-success" type="button" :disabled="!canClaim || Boolean(busyAction)" @click="claimJob">
            <Coins :size="17" /> Claim
          </button>
          <button class="button button-secondary" type="button" :disabled="!canSettle || Boolean(busyAction)" @click="settleSession">
            <Coins :size="17" /> Settle
          </button>
          <button class="button button-danger" type="button" :disabled="!session || session.status !== 'RUNNING' || Boolean(busyAction)" @click="stopSession">
            <Octagon :size="17" /> Stop
          </button>
        </div>

        <div v-if="busyAction" class="lab-busy" role="status">
          <LoaderCircle class="spinning" :size="18" />
          {{ busyAction }}
        </div>

        <dl class="job-meta lab-job-meta">
          <div>
            <dt>Target</dt>
            <dd>{{ currentJob?.target_id ?? '-' }}</dd>
          </div>
          <div>
            <dt>Points</dt>
            <dd>{{ currentJob?.points ?? '-' }}</dd>
          </div>
          <div>
            <dt>Follow</dt>
            <dd>{{ followStatus ? (followStatus.following ? 'true' : 'false') : '-' }}</dd>
          </div>
        </dl>

        <a
          v-if="currentJob?.url"
          class="job-url lab-url"
          :href="mockProfileUrl(currentJob.url)"
          target="_blank"
          rel="noopener"
        >
          <ExternalLink :size="16" aria-hidden="true" />
          <span>{{ mockProfileUrl(currentJob.url) }}</span>
        </a>
      </section>

      <aside class="panel lab-log-panel">
        <div class="panel-heading compact-heading">
          <h2>Lab state</h2>
        </div>

        <div class="lab-counters">
          <span>Fetched <strong>{{ session?.jobs_fetched ?? 0 }}</strong></span>
          <span>Opened <strong>{{ session?.jobs_opened ?? 0 }}</strong></span>
          <span>Clicked <strong>{{ session?.jobs_clicked ?? 0 }}</strong></span>
          <span>Verified <strong>{{ session?.jobs_action_verified ?? 0 }}</strong></span>
          <span>Claimed <strong>{{ session?.jobs_claimed ?? 0 }}</strong></span>
          <span>Points <strong>{{ session?.points_earned ?? 0 }}</strong></span>
        </div>

        <ul class="event-list lab-event-list">
          <li v-for="event in runnerEvents.slice().reverse()" :key="`${event.ts}-${event.event}-${event.job_id ?? event.run_id ?? ''}`">
            <time>{{ new Date(event.ts).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) }}</time>
            <span>{{ formatRunnerEvent(event) }}</span>
          </li>
          <li v-for="event in events" :key="event">
            <time>{{ event.slice(0, 8) }}</time>
            <span>{{ event.slice(9) }}</span>
          </li>
        </ul>
        <p v-if="!events.length && !runnerEvents.length" class="log-empty">No lab events</p>
      </aside>
    </div>
  </main>
</template>
