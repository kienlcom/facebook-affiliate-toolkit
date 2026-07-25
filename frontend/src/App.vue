<script setup lang="ts">
import { PanelsTopLeft, ShieldCheck } from '@lucide/vue'
</script>

<template>
  <div class="app-frame">
    <header class="app-header">
      <router-link class="brand" to="/" aria-label="Facebook TDS Job Assistant">
        <span class="brand-mark"><PanelsTopLeft :size="19" aria-hidden="true" /></span>
        <span>
          <strong>Facebook TDS Job Assistant</strong>
          <small>Local workspace</small>
        </span>
      </router-link>
      <div class="security-mark" title="Token TDS chỉ được giữ ở backend">
        <ShieldCheck :size="17" aria-hidden="true" />
        <span>Server-side token</span>
      </div>
    </header>
    <router-view />
  </div>
</template>
