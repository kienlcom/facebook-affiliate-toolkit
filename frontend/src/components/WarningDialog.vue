<script setup lang="ts">
import { AlertTriangle, X } from '@lucide/vue'
import { ref } from 'vue'

import type { WarningType } from '../api/types'

defineProps<{
  open: boolean
  busy: boolean
}>()

const emit = defineEmits<{
  close: []
  submit: [warningType: WarningType, note: string | null]
}>()

const warningType = ref<WarningType>('CHECKPOINT')
const note = ref('')

function submit(): void {
  emit('submit', warningType.value, note.value.trim() || null)
}
</script>

<template>
  <div v-if="open" class="dialog-backdrop" role="presentation" @click.self="$emit('close')">
    <section class="dialog" role="dialog" aria-modal="true" aria-labelledby="warning-title">
      <div class="panel-heading">
        <h2 id="warning-title"><AlertTriangle :size="19" /> Cảnh báo tài khoản</h2>
        <button class="icon-button" type="button" title="Đóng" :disabled="busy" @click="$emit('close')">
          <X :size="18" />
        </button>
      </div>
      <label class="field-label">
        <span>Loại cảnh báo</span>
        <select v-model="warningType">
          <option value="CHECKPOINT">Checkpoint</option>
          <option value="TEMPORARY_BLOCK">Temporary block</option>
          <option value="IDENTITY_VERIFICATION">Identity verification</option>
          <option value="FEATURE_UNAVAILABLE">Feature unavailable</option>
          <option value="SUSPICIOUS_ACTIVITY">Suspicious activity</option>
          <option value="OTHER">Khác</option>
        </select>
      </label>
      <label class="field-label">
        <span>Ghi chú</span>
        <textarea v-model="note" rows="3" maxlength="1000" />
      </label>
      <div class="dialog-actions">
        <button class="button button-secondary" type="button" :disabled="busy" @click="$emit('close')">Hủy</button>
        <button class="button button-danger" type="button" :disabled="busy" @click="submit">
          <AlertTriangle :size="17" /> Dừng phiên
        </button>
      </div>
    </section>
  </div>
</template>
