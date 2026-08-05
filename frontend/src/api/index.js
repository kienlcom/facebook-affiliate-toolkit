import axios from 'axios'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
})

export const channelApi = {
  list: () => api.get('/api/channels'),
  create: (payload) => api.post('/api/channels', payload),
  update: (id, payload) => api.put(`/api/channels/${id}`, payload),
  remove: (id) => api.delete(`/api/channels/${id}`)
}

export const controllerApi = {
  start: (config) => api.post('/api/controller/start', config),
  stop: () => api.post('/api/controller/stop'),
  buy: () => api.post('/api/controller/buy'),
  skip: () => api.post('/api/controller/skip'),
  status: () => api.get('/api/controller/status')
}
