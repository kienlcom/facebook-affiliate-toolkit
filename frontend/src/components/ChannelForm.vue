<script setup>
import { Plus } from '@lucide/vue'
import { reactive, ref } from 'vue'

import { useChannelStore } from '../stores/useChannelStore'

const store = useChannelStore()
const saving = ref(false)
const form = reactive({
  channel_name: '',
  channel_url: ''
})

async function submit() {
  if (!form.channel_name.trim() || !form.channel_url.trim()) return

  saving.value = true
  try {
    await store.addChannel({
      channel_name: form.channel_name.trim(),
      channel_url: form.channel_url.trim(),
      is_active: true
    })
    form.channel_name = ''
    form.channel_url = ''
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <form class="channel-form" @submit.prevent="submit">
    <label class="field-label">
      <span>Tên kênh</span>
      <input v-model="form.channel_name" type="text" placeholder="@tenkenh" autocomplete="off" />
    </label>

    <label class="field-label">
      <span>URL TikTok</span>
      <input v-model="form.channel_url" type="url" placeholder="https://www.tiktok.com/@tenkenh" />
    </label>

    <button class="button button-primary" type="submit" :disabled="saving">
      <Plus :size="17" aria-hidden="true" />
      <span>Thêm kênh</span>
    </button>
  </form>
</template>
