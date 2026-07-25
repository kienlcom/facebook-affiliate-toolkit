<script setup lang="ts">
import { ArrowRight, Octagon, Play, Server, ShieldCheck } from '@lucide/vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import AccountCard from '../components/AccountCard.vue'
import ProfileSelector from '../components/ProfileSelector.vue'
import StatusIndicator from '../components/StatusIndicator.vue'
import { useAccountStore } from '../stores/account'
import { useSessionStore } from '../stores/session'

const router = useRouter()
const accountStore = useAccountStore()
const sessionStore = useSessionStore()
const selectedProfile = ref('')

const apiReady = computed(
  () => accountStore.backendStatus === 'online' && accountStore.profiles.length > 0 && Boolean(accountStore.account)
)
const activeSession = computed(() =>
  sessionStore.current?.status === 'RUNNING' ? sessionStore.current : null
)

watch(
  () => accountStore.profiles,
  (profiles) => {
    if (!selectedProfile.value && profiles[0]) {
      selectedProfile.value = profiles[0].key
    }
  },
  { immediate: true }
)

onMounted(async () => {
  await accountStore.loadDashboard()
  if (accountStore.backendStatus === 'online') {
    await sessionStore.loadActive().catch(() => undefined)
  }
})

async function startSession(): Promise<void> {
  if (!selectedProfile.value) return
  try {
    const session = await sessionStore.start(selectedProfile.value)
    await router.push({ name: 'session', params: { id: session.id } })
  } catch (caught) {
    if (
      caught instanceof Error &&
      'code' in caught &&
      caught.code === 'SESSION_ALREADY_RUNNING' &&
      'details' in caught
    ) {
      const sessionId = (caught.details as Record<string, unknown> | undefined)?.session_id
      if (typeof sessionId === 'string') {
        await router.push({ name: 'session', params: { id: sessionId } })
      }
    }
    return
  }
}

async function resumeSession(): Promise<void> {
  if (!activeSession.value) return
  await router.push({ name: 'session', params: { id: activeSession.value.id } })
}

async function stopActiveSession(): Promise<void> {
  if (!activeSession.value) return
  try {
    await sessionStore.stop(activeSession.value.id)
  } catch {
    return
  }
}
</script>

<template>
  <main class="page dashboard-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">Workspace</p>
        <h1>Bảng điều khiển</h1>
      </div>
      <div class="health-cluster">
        <StatusIndicator
          :label="accountStore.backendStatus === 'online' ? 'Backend online' : accountStore.backendStatus === 'checking' ? 'Đang kiểm tra' : 'Backend offline'"
          :status="accountStore.backendStatus"
        />
        <StatusIndicator
          :label="apiReady ? 'TDS sẵn sàng' : 'TDS chưa sẵn sàng'"
          :status="apiReady ? 'online' : accountStore.loading ? 'checking' : 'offline'"
        />
      </div>
    </div>

    <div v-if="accountStore.error || sessionStore.error" class="alert alert-error" role="alert">
      {{ accountStore.error ?? sessionStore.error }}
    </div>

    <div class="dashboard-grid">
      <AccountCard
        :account="accountStore.account"
        :loading="accountStore.loading"
        @refresh="accountStore.loadDashboard"
      />

      <section class="panel start-panel" aria-labelledby="start-title">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">Phiên mới</p>
            <h2 id="start-title">Facebook Page</h2>
          </div>
          <Server :size="20" aria-hidden="true" />
        </div>
        <template v-if="activeSession">
          <div class="active-session-summary">
            <span>Phiên đang chạy</span>
            <strong>{{ activeSession.id.slice(0, 8) }}</strong>
            <small>{{ activeSession.profile_key }}</small>
          </div>
          <div class="start-actions">
            <button class="button button-primary resume-button" type="button" @click="resumeSession">
              Tiếp tục phiên <ArrowRight :size="17" />
            </button>
            <button
              class="button button-danger dashboard-stop-button"
              type="button"
              :disabled="sessionStore.loading"
              @click="stopActiveSession"
            >
              <Octagon :size="17" /> Dừng phiên
            </button>
          </div>
        </template>
        <template v-else>
          <ProfileSelector
            v-model="selectedProfile"
            :profiles="accountStore.profiles"
            :disabled="accountStore.loading || sessionStore.loading"
          />
          <div class="guardrail-row">
            <span><ShieldCheck :size="16" /> {{ accountStore.profiles[0]?.minimum_claim_wait_seconds ?? 3 }}s min-wait</span>
            <span>{{ accountStore.profiles[0]?.settlement_threshold ?? 5 }} jobs / batch</span>
          </div>
          <button
            class="button button-primary start-button"
            type="button"
            :disabled="!apiReady || !selectedProfile || sessionStore.loading"
            @click="startSession"
          >
            <Play :size="17" fill="currentColor" /> Bắt đầu phiên
            <ArrowRight :size="17" />
          </button>
        </template>
      </section>
    </div>
  </main>
</template>
