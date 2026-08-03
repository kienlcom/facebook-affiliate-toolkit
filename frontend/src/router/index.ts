import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: () => import('../views/DashboardView.vue')
    },
    {
      path: '/mock-lab',
      name: 'mock-lab',
      component: () => import('../views/MockLabView.vue')
    },
    {
      path: '/coming-soon',
      name: 'coming-soon',
      component: () => import('../views/ComingSoonView.vue')
    },
    {
      path: '/sessions/:id',
      name: 'session',
      component: () => import('../views/SessionView.vue'),
      props: true
    }
  ]
})
