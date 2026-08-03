<script setup lang="ts">
import { Construction, FlaskConical, LayoutDashboard, PanelsTopLeft, ShieldCheck } from '@lucide/vue'
</script>

<template>
  <div class="app-frame">
    <aside class="app-sidebar" aria-label="Primary navigation">
      <router-link class="brand" to="/" aria-label="Facebook TDS Job Assistant">
        <span class="brand-mark"><PanelsTopLeft :size="19" aria-hidden="true" /></span>
        <span>
          <strong>Facebook TDS Job Assistant</strong>
          <small>Local workspace</small>
        </span>
      </router-link>

      <nav class="sidebar-nav">
        <router-link class="sidebar-link" to="/">
          <LayoutDashboard :size="18" aria-hidden="true" />
          <span>Dashboard</span>
        </router-link>
        <router-link class="sidebar-link" to="/mock-lab">
          <FlaskConical :size="18" aria-hidden="true" />
          <span>Mock Lab</span>
        </router-link>
        <router-link class="sidebar-link" to="/coming-soon">
          <Construction :size="18" aria-hidden="true" />
          <span>Chuẩn bị</span>
        </router-link>
      </nav>

      <div class="security-mark" title="Token TDS chi duoc giu o backend">
        <ShieldCheck :size="17" aria-hidden="true" />
        <span>Server-side token</span>
      </div>
    </aside>

    <div class="app-content">
      <router-view />
    </div>
  </div>
</template>
