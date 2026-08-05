<script setup>
import ChannelList from '../components/ChannelList.vue'
import Controller from '../components/Controller.vue'
</script>

<template>
  <main class="page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">AirPlay + LonelyScreen</p>
        <h1>TikTok Shop Auto Scroll</h1>
      </div>
    </div>

    <div class="tiktok-shop-layout">
      <ChannelList />
      <Controller />
    </div>
  </main>
</template>
