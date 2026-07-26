# GO / NO-GO

Current decision: GO

Decision date: 2026-07-25

Scope: production provider support for the verified `facebook_page` profile
only.

## Evidence

- Live profile request succeeded and exposed verified username/balance fields.
- Invalid token was identified from a sanitized real response.
- Live `facebook_page` jobs were received with verified ID, code, action, and
  URL mapping.
- Empty jobs and account-not-configured responses are distinct from auth
  errors.
- Five Facebook actions were completed and manually confirmed by the user.
- Review requests succeeded with `facebook_page_cache` and one `job.code`.
- Settlement succeeded with `facebook_page` and `facebook_api`.
- Success credited 6,300 points and returned the updated balance.
- Too-fast, business rejection, and claim auth errors were observed and
  classified by response body despite HTTP 200.
- All required fixtures are sanitized and contain no token or cookie.
- Offline parser prototype tests pass.
- No Facebook cookie, CAPTCHA, bypass, or browser automation is required.

## Constraints Carried Into Phase 2

- Only `facebook_page` is enabled.
- Mapping comes from `config/job_profiles.json`; it is not duplicated as an
  unverified endpoint contract.
- Every response body is parsed; HTTP 200 is not sufficient for success.
- Claim review requires manual confirmation and server-side minimum wait.
- Settlement is a separate operation after the cache threshold.
- HTTP 429 opens the persisted circuit breaker and honors `Retry-After`.

No unknown issue blocks the verified MVP profile.

## Additional profile: facebook_follow

Current decision: `PILOT_PENDING_LIVE_CLAIM`.

The official Postman mapping and a sanitized live get-jobs response are
verified. Eight jobs were available on 2026-07-26. The profile may be used only
for the manual pilot flow; promote it to `GO` only after review-cache and
settlement responses succeed for a manually completed batch.
