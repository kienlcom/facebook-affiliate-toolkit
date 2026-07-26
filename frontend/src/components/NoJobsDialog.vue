<script setup lang="ts">
import { ArrowRight, Inbox, Octagon } from '@lucide/vue'

defineProps<{
  open: boolean
  busy: boolean
}>()

defineEmits<{
  stop: []
  continue: []
}>()
</script>

<template>
  <div v-if="open" class="dialog-backdrop" role="presentation">
    <section
      class="dialog"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="no-jobs-title"
      aria-describedby="no-jobs-description"
    >
      <div class="panel-heading">
        <h2 id="no-jobs-title"><Inbox :size="19" /> Không có nhiệm vụ</h2>
      </div>
      <p id="no-jobs-description" class="dialog-message">
        TDS hiện không trả về nhiệm vụ mới. Nút lấy nhiệm vụ sẽ tạm khóa 20 giây
        để tránh gửi yêu cầu liên tục.
      </p>
      <div class="dialog-actions">
        <button
          class="button button-danger no-jobs-stop"
          type="button"
          :disabled="busy"
          @click="$emit('stop')"
        >
          <Octagon :size="17" /> Dừng phiên
        </button>
        <button
          class="button button-primary no-jobs-continue"
          type="button"
          :disabled="busy"
          @click="$emit('continue')"
        >
          Tiếp tục <ArrowRight :size="17" />
        </button>
      </div>
    </section>
  </div>
</template>
