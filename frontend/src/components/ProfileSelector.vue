<script setup lang="ts">
import { Layers3 } from '@lucide/vue'

import type { JobProfile } from '../api/types'

defineProps<{
  profiles: JobProfile[]
  modelValue: string
  disabled?: boolean
}>()

defineEmits<{
  'update:modelValue': [value: string]
}>()
</script>

<template>
  <label class="field-label" for="profile-select">
    <span><Layers3 :size="16" aria-hidden="true" /> Loại nhiệm vụ</span>
    <select
      id="profile-select"
      :value="modelValue"
      :disabled="disabled"
      @change="$emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
    >
      <option value="" disabled>Chọn profile</option>
      <option v-for="profile in profiles" :key="profile.key" :value="profile.key">
        {{ profile.display_name }}
      </option>
    </select>
  </label>
</template>
