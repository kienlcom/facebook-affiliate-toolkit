import { expect, test, type Page, type Route } from '@playwright/test'

const sessionId = '70eb165e-5984-45cf-893b-cd2a31560a98'
const jobId = '46d8970e-ccf8-47c8-900d-1bea28f48093'
const now = new Date()

const account = {
  account_id: 'local',
  display_name: 'Local Facebook account',
  tds: {
    username: 'pilot_account',
    balance: 12500,
    status: 'ready'
  }
}

const profile = {
  key: 'facebook_page',
  display_name: 'Facebook Page',
  provider: 'tds',
  platform: 'facebook',
  minimum_claim_wait_seconds: 3,
  settlement_threshold: 5
}

const summary = {
  session: {
    id: sessionId,
    account_id: 'local',
    status: 'RUNNING',
    profile_key: 'facebook_page',
    started_at: new Date(now.getTime() - 78_000).toISOString(),
    ended_at: null,
    stop_reason: null,
    limits: {
      max_jobs: 20,
      max_duration_minutes: 30
    }
  },
  counters: {
    fetched: 5,
    opened: 2,
    confirmed: 1,
    claimed: 1,
    failed: 0,
    points_earned: 600
  },
  elapsed_seconds: 78,
  remaining_jobs: 15,
  jobs: [
    {
      id: jobId,
      session_id: sessionId,
      external_id: '100074844057308',
      profile_key: 'facebook_page',
      url: 'https://www.facebook.com/100074844057308',
      action_label: 'Theo doi Facebook Page',
      state: 'WAITING_USER',
      fetched_at: new Date(now.getTime() - 24_000).toISOString(),
      opened_at: new Date(now.getTime() - 10_000).toISOString(),
      user_confirmed_at: null,
      claimed_at: null
    }
  ]
}

async function fulfillJson(route: Route, body: unknown): Promise<void> {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body)
  })
}

async function mockApi(page: Page): Promise<void> {
  await page.routeWebSocket('**/ws/**', () => undefined)
  await page.route('**/health', (route) => fulfillJson(route, { status: 'ok' }))
  await page.route('**/api/account/profile', (route) => fulfillJson(route, account))
  await page.route('**/api/profiles', (route) => fulfillJson(route, [profile]))
  await page.route(`**/api/sessions/${sessionId}/summary`, (route) =>
    fulfillJson(route, summary)
  )
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const fitsViewport = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth
  )
  expect(fitsViewport).toBe(true)
}

test('dashboard renders the local account on desktop', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await mockApi(page)
  await page.goto('/')

  await expect(page.locator('h1')).toBeVisible()
  await expect(page.getByText('Backend online')).toBeVisible()
  await expect(page.getByText('pilot_account')).toBeVisible()
  await expect(page.locator('.start-button')).toBeEnabled()
  await expectNoHorizontalOverflow(page)

  await page.screenshot({
    path: 'test-results/phase4-dashboard-desktop.png',
    fullPage: true
  })
})

test('session workspace remains usable on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockApi(page)
  await page.goto(`/sessions/${sessionId}`)

  await expect(page.getByRole('heading', { name: 'Facebook Page', exact: true })).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'Theo doi Facebook Page', exact: true })
  ).toBeVisible()
  await expect(page.getByTestId('complete-button')).toBeEnabled()
  await expect(page.getByText('600')).toBeVisible()
  await expectNoHorizontalOverflow(page)

  await page.screenshot({
    path: 'test-results/phase4-session-mobile.png',
    fullPage: true
  })
})
