<script setup>
import { Clock, MousePointer2, Play, ShoppingCart, SkipForward, Square } from '@lucide/vue'
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'

import { controllerApi } from '../api'

const status = ref({
  status: 'stopped',
  running: false,
  mode: 'stopped',
  active_channels_count: 0,
  last_error: ''
})
const busyAction = ref('')
const error = ref('')
const config = reactive({
  scroll_interval: 30,
  scroll_x: 500,
  scroll_y_start: 780,
  scroll_y_end: 240
})
let timer = 0

const statusLabel = computed(() => {
  if (status.value.running) return 'Đang chạy'
  if (status.value.mode === 'waiting_for_buy') return 'Đang chờ mua'
  return 'Đã dừng'
})

const statusClass = computed(() => (status.value.running ? 'status-positive' : 'status-negative'))

function applyStatus(data) {
  status.value = data
  if (data.config) Object.assign(config, data.config)
}

async function refreshStatus() {
  try {
    const { data } = await controllerApi.status()
    applyStatus(data)
  } catch (requestError) {
    error.value = requestError?.response?.data?.detail || 'Không đọc được trạng thái controller'
  }
}

async function run(action, request) {
  busyAction.value = action
  error.value = ''
  try {
    const { data } = await request()
    applyStatus(data)
  } catch (requestError) {
    error.value = requestError?.response?.data?.detail || 'Lệnh điều khiển không thực hiện được'
  } finally {
    busyAction.value = ''
  }
}

function start() {
  run('start', () => controllerApi.start({ ...config }))
}

function stop() {
  run('stop', controllerApi.stop)
}

function buy() {
  run('buy', controllerApi.buy)
}

function skip() {
  run('skip', controllerApi.skip)
}

onMounted(() => {
  refreshStatus()
  timer = window.setInterval(refreshStatus, 3000)
})

onUnmounted(() => {
  window.clearInterval(timer)
})
</script>

<template>
  <section class="panel tiktok-panel controller-panel">
    <div class="panel-heading compact-heading">
      <div>
        <p class="eyebrow">Điều khiển</p>
        <h2>Auto scroll</h2>
      </div>
      <span class="status-indicator" :class="statusClass">
        <span class="status-dot" />
        {{ statusLabel }}
      </span>
    </div>

    <div class="controller-actions">
      <button class="button start-scroll-button" type="button" :disabled="busyAction === 'start'" @click="start">
        <Play :size="22" aria-hidden="true" />
        <span>START</span>
      </button>
      <button class="button button-danger control-button" type="button" :disabled="busyAction === 'stop'" @click="stop">
        <Square :size="18" aria-hidden="true" />
        <span>STOP</span>
      </button>
      <button class="button buy-button control-button" type="button" :disabled="busyAction === 'buy'" @click="buy">
        <ShoppingCart :size="18" aria-hidden="true" />
        <span>MUA</span>
      </button>
      <button class="button skip-button control-button" type="button" :disabled="busyAction === 'skip'" @click="skip">
        <SkipForward :size="18" aria-hidden="true" />
        <span>SKIP</span>
      </button>
    </div>

    <p v-if="error || status.last_error" class="alert alert-error">
      {{ error || status.last_error }}
    </p>

    <div class="config-grid">
      <label class="field-label interval-control">
        <span><Clock :size="15" aria-hidden="true" /> Interval: {{ config.scroll_interval }}s</span>
        <input v-model.number="config.scroll_interval" type="range" min="10" max="60" step="1" />
      </label>

      <label class="field-label">
        <span><MousePointer2 :size="15" aria-hidden="true" /> X</span>
        <input v-model.number="config.scroll_x" type="number" min="0" />
      </label>

      <label class="field-label">
        <span>Y start</span>
        <input v-model.number="config.scroll_y_start" type="number" min="0" />
      </label>

      <label class="field-label">
        <span>Y end</span>
        <input v-model.number="config.scroll_y_end" type="number" min="0" />
      </label>
    </div>

    <dl class="controller-meta">
      <div>
        <dt>Kênh bật</dt>
        <dd>{{ status.active_channels_count || 0 }}</dd>
      </div>
      <div>
        <dt>Trạng thái</dt>
        <dd>{{ status.status }}</dd>
      </div>
    </dl>
  </section>
</template>
