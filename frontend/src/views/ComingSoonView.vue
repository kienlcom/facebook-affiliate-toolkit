<script setup lang="ts">
import { Construction } from '@lucide/vue'
</script>

<template>
  <main class="page coming-soon-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">Next workspace</p>
        <h1>Chuẩn bị implement</h1>
      </div>
    </div>

    <section class="panel placeholder-panel">
      <Construction :size="28" aria-hidden="true" />
      <div>
        <h2>Đang chuẩn bị</h2>
        <p>Không gian này được giữ sẵn cho chức năng tiếp theo.</p>
      </div>
    </section>
  </main>
</template>
