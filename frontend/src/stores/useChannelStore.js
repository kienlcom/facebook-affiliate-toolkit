import { defineStore } from 'pinia'

import { channelApi } from '../api'

export const useChannelStore = defineStore('tiktokChannels', {
  state: () => ({
    channels: [],
    loading: false,
    error: ''
  }),

  actions: {
    async fetchChannels() {
      this.loading = true
      this.error = ''
      try {
        const { data } = await channelApi.list()
        this.channels = data
      } catch (error) {
        this.error = error?.response?.data?.detail || 'Không tải được danh sách kênh'
      } finally {
        this.loading = false
      }
    },

    async addChannel(payload) {
      this.error = ''
      try {
        await channelApi.create(payload)
        await this.fetchChannels()
      } catch (error) {
        this.error = error?.response?.data?.detail || 'Không thêm được kênh'
        throw error
      }
    },

    async deleteChannel(id) {
      this.error = ''
      try {
        await channelApi.remove(id)
        this.channels = this.channels.filter((channel) => channel.id !== id)
      } catch (error) {
        this.error = error?.response?.data?.detail || 'Không xóa được kênh'
      }
    },

    async updateChannel(id, payload) {
      this.error = ''
      try {
        const { data } = await channelApi.update(id, payload)
        this.channels = this.channels.map((channel) => (channel.id === id ? data : channel))
      } catch (error) {
        this.error = error?.response?.data?.detail || 'Không cập nhật được kênh'
      }
    },

    async toggleChannel(channel) {
      await this.updateChannel(channel.id, { is_active: !channel.is_active })
    }
  }
})
