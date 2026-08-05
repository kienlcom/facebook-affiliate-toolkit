<script setup>
import { RefreshCw, Trash2 } from '@lucide/vue'
import { onMounted } from 'vue'

import { useChannelStore } from '../stores/useChannelStore'
import ChannelForm from './ChannelForm.vue'

const store = useChannelStore()

onMounted(() => {
  store.fetchChannels()
})
</script>

<template>
  <section class="panel tiktok-panel">
    <div class="panel-heading compact-heading">
      <div>
        <p class="eyebrow">TikTok Shop</p>
        <h2>Kênh yêu thích</h2>
      </div>
      <button class="icon-button" type="button" title="Tải lại" @click="store.fetchChannels">
        <RefreshCw :size="16" aria-hidden="true" />
      </button>
    </div>

    <ChannelForm />

    <p v-if="store.error" class="alert alert-error">{{ store.error }}</p>

    <div class="channel-list" aria-live="polite">
      <p v-if="store.loading" class="queue-empty">Đang tải...</p>
      <p v-else-if="store.channels.length === 0" class="queue-empty">Chưa có kênh nào.</p>

      <article v-for="channel in store.channels" :key="channel.id" class="channel-item">
        <label class="auto-open-toggle channel-toggle">
          <input
            type="checkbox"
            :checked="channel.is_active"
            @change="store.toggleChannel(channel)"
          />
          <span class="toggle-track" aria-hidden="true"><span /></span>
        </label>

        <div class="channel-copy">
          <strong>{{ channel.channel_name }}</strong>
          <a :href="channel.channel_url" target="_blank" rel="noreferrer">{{ channel.channel_url }}</a>
        </div>

        <button
          class="icon-button danger-icon"
          type="button"
          title="Xóa kênh"
          @click="store.deleteChannel(channel.id)"
        >
          <Trash2 :size="16" aria-hidden="true" />
        </button>
      </article>
    </div>
  </section>
</template>
