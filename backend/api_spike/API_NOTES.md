# TDS API Spike Notes

Status: verified on 2026-07-25 with sanitized live responses.

No real token, cookie, Facebook credential, or unredacted authorization data is
stored in this directory.

## Profile

- Method: `GET`
- URL: `https://traodoisub.com/api/`
- Query: `fields=profile&access_token=[REDACTED]`
- Headers: none required
- Status: HTTP 200
- Content-Type: `application/json; charset=UTF-8`
- Success discriminator: `success == 200`
- Data field: `data`
- Username field: `data.user`
- Balance field: `data.xu` (numeric string)
- Secondary balance field: `data.xudie` (numeric string)
- Facebook ID field: `data.idfb`
- Invalid token discriminator: non-empty `error` containing `Access token`
- Fixtures: `profile_success.json`, `profile_invalid_token.json`

Account selection was separately verified with:

```text
GET /api/?fields=run&id={facebook_id}&access_token=[REDACTED]
```

## Get Jobs

- MVP profile: `facebook_page`
- Method: `GET`
- URL: `https://traodoisub.com/api/`
- Query: `fields=facebook_page&access_token=[REDACTED]`
- Status: HTTP 200
- Jobs field: `data`
- Pending cache field: `cache`
- External ID field: `data[].id`
- Claim code field: `data[].code`
- Action field: `data[].type`
- URL mapping: `https://www.facebook.com/{data[].id}`
- Empty jobs discriminator: `data` is an empty list; this is not an auth error
- Account-not-configured discriminator: non-empty `error` containing
  `chưa được thêm vào cấu hình`
- Rate limit: not encountered during the spike; production handling follows
  design v2.0 sections 20.4-20.5
- Fixtures: `jobs_success.json`, `jobs_empty.json`,
  `jobs_account_not_configured.json`

## Claim

Claim for `facebook_page` is a verified two-step contract.

### Step 1: submit a manually completed job for review

- Method: `GET`
- URL: `https://traodoisub.com/api/coin/`
- Query:
  `type=facebook_page_cache&id={job.code}&access_token=[REDACTED]`
- ID format: one job `code`, not the Facebook external ID
- Success discriminator: integer `cache >= 0`, `msg == "Thành công"`, and no
  non-empty `error`
- Fixture: `claim_cache_success.json`

The user manually completed and confirmed each Facebook action before every
review request.

### Step 2: settle cached jobs

- Method: `GET`
- URL: `https://traodoisub.com/api/coin/`
- Query:
  `type=facebook_page&id=facebook_api&access_token=[REDACTED]`
- Settlement threshold: 5 cached jobs
- Success discriminator: `success == 200`
- Balance field: `data.xu`
- Accepted jobs field: `data.job_success`
- Points earned field: `data.xu_them`
- Message field: `data.msg`
- Fixture: `claim_success.json`

### Errors

- Too fast: non-empty `error` containing `quá nhanh`; optional numeric
  `countdown`. Fixture: `claim_too_fast.json`.
- Business rejection: any other non-auth claim `error`. The observed example
  was settlement before enough cached jobs. Fixture: `claim_rejected.json`.
- Auth error: non-empty `error` containing `Access token`. Fixture:
  `claim_auth_error.json`.
- HTTP 200 alone never means profile, jobs, review, or settlement succeeded.

## Timing

An immediate settlement call after the fifth cache response returned the
too-fast business error. The verified profile uses a conservative
`minimum_claim_wait_seconds = 3`; the backend remains the source of truth for
this wait.

## Verified Profile Mapping

The production mapping is stored in `backend/config/job_profiles.json`:

- `job_field = facebook_page`
- `claim_type = facebook_page_cache`
- `id_format = job.code`
- `settlement_type = facebook_page`
- `settlement_id = facebook_api`
- `settlement_threshold = 5`
- `url_template = https://www.facebook.com/{external_id}`

## Safety Findings

- TDS access token is sufficient for TDS API calls and remains server-side.
- No Facebook cookie was sent to TDS API.
- No CAPTCHA, bypass, UI automation, proxy rotation, or anti-detection
  mechanism was needed.
