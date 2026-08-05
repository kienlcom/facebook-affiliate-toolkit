<script setup lang="ts">
import { ExternalLink, LoaderCircle, Octagon, Play, RefreshCw } from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { normalizeApiError } from '../api/http'
import { reelsApi, type ReelLink, type ReelRunEvent, type ReelRunLogs } from '../api/reels'

const links = ref<ReelLink[]>([])
const run = ref<ReelRunLogs | null>(null)
const dwellSeconds = ref(5)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const busyAction = ref<string | null>(null)
let pollTimer: number | null = null

const isRunning = computed(() => run.value?.status === 'RUNNING' || run.value?.status === 'PENDING')
const enabledLinks = computed(() => links.value.filter((link) => link.enabled))
const canStart = computed(() => enabledLinks.value.length > 0 && !isRunning.value)

// Link đang được lướt suy ra từ event mới nhất, không cần thêm endpoint riêng.
const currentSlug = computed(() => {
  const events = run.value?.events ?? []
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const slug = events[index].data?.slug
    if (typeof slug === 'string') return slug
  }
  return null
})

onMounted(() => {
  void loadLinks()
  void refreshRun({ silent: true })
})

onBeforeUnmount(() => {
  stopPolling()
})

async function runAction(label: string, action: () => Promise<void>): Promise<void> {
  busyAction.value = label
  error.value = null
  notice.value = null
  try {
    await action()
  } catch (caught) {
    const normalized = normalizeApiError(caught)
    error.value = `${normalized.code}: ${normalized.message}`
  } finally {
    busyAction.value = null
  }
}

async function loadLinks(): Promise<void> {
  await runAction('load links', async () => {
    links.value = await reelsApi.links()
  })
}

async function refreshRun({ silent = false } = {}): Promise<void> {
  try {
    run.value = await reelsApi.runStatus()
    if (isRunning.value) startPolling()
  } catch (caught) {
    const normalized = normalizeApiError(caught)
    // Chưa từng chạy lần nào là trạng thái bình thường lúc mở trang.
    if (normalized.code === 'REEL_RUN_NOT_FOUND') return
    if (!silent) error.value = `${normalized.code}: ${normalized.message}`
  }
}

async function start(): Promise<void> {
  await runAction('start', async () => {
    await reelsApi.startRun(dwellSeconds.value)
    notice.value = `Bắt đầu lướt ${enabledLinks.value.length} link, mỗi ảnh ${dwellSeconds.value}s`
    await refreshRun()
    startPolling()
  })
}

async function stop(): Promise<void> {
  await runAction('stop', async () => {
    await reelsApi.stopRun()
    notice.value = 'Đã gửi yêu cầu dừng'
    await refreshRun()
  })
}

function startPolling(): void {
  if (pollTimer !== null) return
  pollTimer = window.setInterval(() => {
    void pollOnce()
  }, 700)
}

function stopPolling(): void {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

async function pollOnce(): Promise<void> {
  try {
    run.value = await reelsApi.runStatus()
    if (!isRunning.value) {
      stopPolling()
      notice.value = `Runner ${run.value.status.toLowerCase()}`
    }
  } catch (caught) {
    stopPolling()
    const normalized = normalizeApiError(caught)
    error.value = `${normalized.code}: ${normalized.message}`
  }
}

function formatEvent(event: ReelRunEvent): string {
  const data = event.data ?? {}
  const parts: string[] = [event.event]
  if (typeof data.title === 'string') parts.push(data.title)
  if (typeof data.index === 'number') parts.push(`ảnh ${data.index}`)
  if (typeof data.images_viewed === 'number') parts.push(`${data.images_viewed} ảnh`)
  if (typeof data.links === 'number') parts.push(`${data.links} link`)
  if (typeof data.error === 'string') parts.push(data.error)
  return parts.join(' · ')
}

function formatTime(ts: string): string {
  return new Date(ts).toLocaleTimeString('vi-VN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}
</script>

<template>
  <main class="page reel-runner-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">Reel runner</p>
        <h1>Chuẩn bị</h1>
      </div>
      <button class="icon-button" type="button" title="Tải lại danh sách link" @click="loadLinks">
        <RefreshCw :size="16" />
      </button>
    </div>

    <div v-if="error" class="alert alert-error" role="alert">{{ error }}</div>
    <div v-if="notice" class="alert alert-success" role="status">{{ notice }}</div>

    <section class="panel">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">Bảng reel_links</p>
          <h2>{{ links.length }} link · {{ enabledLinks.length }} đang bật</h2>
        </div>
        <span v-if="run" class="state-badge" :data-state="run.status">{{ run.status }}</span>
      </div>

      <div class="reel-controls">
        <label class="field-label">
          <span>Chờ mỗi ảnh (giây)</span>
          <input v-model.number="dwellSeconds" type="number" min="1" max="600" :disabled="isRunning" />
        </label>
        <button class="button button-primary" type="button" :disabled="!canStart || Boolean(busyAction)" @click="start">
          <Play :size="17" fill="currentColor" /> Start
        </button>
        <button class="button button-danger" type="button" :disabled="!isRunning || Boolean(busyAction)" @click="stop">
          <Octagon :size="17" /> Stop
        </button>
        <span v-if="busyAction" class="reel-busy"><LoaderCircle class="spinning" :size="16" /> {{ busyAction }}</span>
      </div>

      <div class="reel-table-wrap">
        <table class="reel-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Tiêu đề</th>
              <th>Slug</th>
              <th>URL</th>
              <th>Số ảnh</th>
              <th>Bật</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="link in links"
              :key="link.id"
              :class="{ 'reel-row-active': link.slug === currentSlug && isRunning }"
            >
              <td>{{ link.sort_order }}</td>
              <td>{{ link.title }}</td>
              <td><code>{{ link.slug }}</code></td>
              <td>
                <a :href="link.absolute_url" target="_blank" rel="noopener">
                  <ExternalLink :size="14" aria-hidden="true" />
                  <span>{{ link.url }}</span>
                </a>
              </td>
              <td>{{ link.image_count }}</td>
              <td>{{ link.enabled ? 'có' : 'không' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="!links.length" class="log-empty">Bảng reel_links đang rỗng</p>
      </div>
    </section>

    <section class="panel">
      <div class="panel-heading compact-heading">
        <h2>Tiến trình</h2>
      </div>

      <div class="lab-counters">
        <span>Link xong <strong>{{ run?.result?.links_completed ?? 0 }}</strong></span>
        <span>Link lỗi <strong>{{ run?.result?.links_failed ?? 0 }}</strong></span>
        <span>Ảnh đã xem <strong>{{ run?.result?.images_viewed ?? 0 }}</strong></span>
        <span>Chờ mỗi ảnh <strong>{{ run?.dwell_seconds ?? dwellSeconds }}s</strong></span>
      </div>

      <ul class="event-list">
        <li v-for="(event, index) in (run?.events ?? []).slice().reverse()" :key="`${event.ts}-${index}`">
          <time>{{ formatTime(event.ts) }}</time>
          <span>{{ formatEvent(event) }}</span>
        </li>
      </ul>
      <p v-if="!run?.events?.length" class="log-empty">Chưa có sự kiện nào</p>
    </section>
  </main>
</template>

<style scoped>
.reel-controls {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 12px;
  margin: 16px 0 20px;
}

.reel-controls input {
  width: 110px;
}

.reel-busy {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--muted);
}

.reel-table-wrap {
  overflow-x: auto;
}

.reel-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.reel-table th,
.reel-table td {
  padding: 9px 12px;
  text-align: left;
  border-bottom: 1px solid rgba(120, 140, 160, .2);
  white-space: nowrap;
}

.reel-table th {
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  font-size: 11px;
  letter-spacing: .04em;
}

.reel-table a {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.reel-row-active td {
  background: rgba(64, 158, 255, .12);
  font-weight: 600;
}
</style>
