<script setup lang="ts">
import { CircleUserRound, Coins, RefreshCw } from '@lucide/vue'

import type { AccountProfile } from '../api/types'

defineProps<{
  account: AccountProfile | null
  loading: boolean
}>()

defineEmits<{
  refresh: []
}>()
</script>

<template>
  <section class="panel account-panel" aria-labelledby="account-title">
    <div class="panel-heading">
      <div>
        <p class="eyebrow">Tài khoản cục bộ</p>
        <h2 id="account-title">{{ account?.display_name ?? 'Đang tải' }}</h2>
      </div>
      <button class="icon-button" type="button" title="Làm mới tài khoản" :disabled="loading" @click="$emit('refresh')">
        <RefreshCw :size="17" :class="{ spinning: loading }" aria-hidden="true" />
      </button>
    </div>
    <div class="account-grid">
      <div class="metric-line">
        <CircleUserRound :size="18" aria-hidden="true" />
        <span>
          <small>TDS username</small>
          <strong>{{ account?.tds.username ?? '—' }}</strong>
        </span>
      </div>
      <div class="metric-line">
        <Coins :size="18" aria-hidden="true" />
        <span>
          <small>Số dư</small>
          <strong>{{ account?.tds.balance?.toLocaleString('vi-VN') ?? '—' }} xu</strong>
        </span>
      </div>
    </div>
  </section>
</template>
