# IMPLEMENTATION PLAN — Facebook TDS Job Assistant (Web)

> **Vai trò của file này:** hướng dẫn *thứ tự thực thi* (execution guide). Nguồn thiết kế chi tiết là
> [`Facebook_TDS_Job_Assistant_Design_v2.0_Web.md`](./Facebook_TDS_Job_Assistant_Design_v2.0_Web.md) — khi có mâu thuẫn, **design v2.1 là nguồn quyết định**.
> File này chỉ nêu: build theo thứ tự nào, mỗi bước tham chiếu mục nào của v2.1, và Definition of Done cho từng phase.

## 0. Context (ngắn)

Web app bán tự động hỗ trợ làm nhiệm vụ Facebook trên TraoDoiSub. Stack: **Vue 3 + TypeScript / FastAPI / PostgreSQL 16**, local-first nhưng multi-user-ready. Người dùng tự thao tác Facebook + xác nhận thủ công; backend là source of truth và chỉ claim sau xác nhận. Chi tiết kiến trúc, schema, REST/WS, invariants: xem v2.1.

Nguyên tắc bất biến (v2.1 §4, §21, §29): backend source of truth · manual confirmation trước claim · token chỉ ở server · tôn trọng 429/Retry-After · dừng khi có cảnh báo Facebook · **không** auto-interaction / proxy rotation / anti-detection.

## 1. Thứ tự thực thi (build order)

Mỗi phase có Definition of Done (DoD). Không sang phase sau khi DoD chưa đạt.

### Phase 0 — API Spike (làm ngay, chặn Phase 2) — v2.0 §10
Thủ công qua Postman, chủ dự án cung cấp response thật.
- Dựng `backend/api_spike/` (API_NOTES.md, sanitized_responses/, fixtures/, parser_prototype.py, GO_NO_GO.md).
- Verify profile (token đúng/sai), get-jobs (1 job type, có job/hết job/chưa cấu hình), claim (type, id đơn/list, min-wait, success/too_fast/rejected/auth).
- Fixtures tối thiểu theo §10.6; `parser_prototype.py` không gọi network, phân biệt no-jobs vs auth error; test pass.
- **DoD:** `GO_NO_GO.md = GO` đủ điều kiện §10.8. Nếu NO-GO → dừng, không hoàn thiện provider (Phase 2).

### Phase 1 — Core backend độc lập hợp đồng API (song song Phase 0) — v2.0 §7,8,11,12,13,14
Build ngay được vì không phụ thuộc field API thật:
1. **Bootstrap monorepo** (§7): `backend/` (pyproject, requirements, .env.example, alembic.ini), `frontend/` để sau, `docker-compose.yml` Postgres 16 (§23.1), `.gitignore`, `docs/` (đã có).
2. **Settings** (§11.2, §14.2): pydantic-settings, fail-fast đủ các điều kiện §11.2 — bao gồm `LINK_OPENER_MODE`/`AUTO_OPEN_ENABLED`/`AUTO_OPEN_INTERVAL_SECONDS` (auto-open chỉ hợp lệ khi `local_browser` + chế độ local; hosted → fail-closed).
3. **Core** (§14.3, §14.4, §19): `logging.py` (JSON + request/account/session/job id), `redaction.py` (§19.2, có test), `security/token_store.py` (Protocol + `LocalEnvTokenStore`).
4. **DB** (§12): SQLAlchemy 2.0 async engine/session, `models.py` (accounts/sessions/jobs/job_attempts/api_calls/app_state), Alembic `0001_init...`, index §12.7. Bootstrap 1 local account (§12.1).
5. **State machine** (§13): enum states, transition table hợp lệ/cấm, `transition()` có optimistic/row-lock + trả `409` khi state đổi (§13.4).
6. **Platform facebook** (§4.5): `platforms/facebook/urls.py` (chỉ https + host Facebook; chặn javascript:/file:/rỗng/malformed).
- **DoD:** unit test §22.1 (settings, redaction, url, state machine) pass; `alembic upgrade head` tạo đủ bảng + FK (§22.4); backend `GET /health` 200.

### Phase 2 — TDS provider (CHỈ sau GO) — v2.0 §14.6, §14.7, §20
- `providers/tds/errors.py` (cây lỗi), `client.py` (httpx async: timeout/DNS/TLS/non-2xx/HTML/invalid-JSON/empty/429+Retry-After/redaction/ghi api_calls), `parser.py` (port từ `parser_prototype.py`, field lấy từ `job_profiles.json` verified — **không hard-code**), `models.py`.
- Retry chỉ lỗi mạng tạm thời (§20.1–20.3); 429 → circuit breaker persist `app_state` (§20.4–20.5).
- **DoD:** provider parser tests §22.2 + integration §22.3 (timeout→ok, 503×3, 429+Retry-After) pass.

### Phase 3 — Services + REST + WebSocket — v2.0 §9, §14.8–14.10, §15, §16, §32
- `sessions/service.py`, `jobs/service.py`, `claims/service.py` (`can_claim` đủ điều kiện §14.9).
- **Local Link Opener + auto-advance (§32)**: `platforms/facebook/opener` dùng `webbrowser.open` (đã validate URL, không shell); orchestrator auto-advance tuần tự (một job WAITING_USER tại một thời điểm, mở job kế sau khi job hiện tại resolved + qua `AUTO_OPEN_INTERVAL_SECONDS`, countdown hủy được). Dừng khi hết queue / đạt limit / account-warning / 429 / token invalid / user pause. **Không** auto-confirm, **không** auto-claim.
- Routes §15 (thêm `GET /health`) + §32.6 (`auto-open`, `auto-open/pause|resume`) + error envelope §15.1.
- `ws/manager.py` + `/ws/sessions/{id}`, event types §16.3 + §32.7 (`job.auto_opened`, `auto_open.next_in`…), không gửi secret §16.4, reconnect resync §16.5.
- **DoD:** integration §22.3 (claim ghi DB, duplicate ignored, **2 claim đồng thời chỉ 1 request tới TDS**, WS nhận event) + §32.9 (auto-advance không mở song song; pause hủy countdown; warning/429/limit dừng auto-open; không auto-claim) pass; manual confirmation + min-wait + session limit enforce server-side.

### Phase 4 — Frontend Vue 3 — v2.0 §17
- Bootstrap Vite + Vue 3 + TS + Pinia + Router + Axios; proxy `/api`,`/ws` → :8000.
- `api/` (typed + WS client), `stores/` (account/session/job/log), `views/` (Dashboard, SessionView), `components/` (AccountCard, ProfileSelector, JobPanel, ConfirmBar, SessionStats, LogPanel).
- Chế độ `frontend_manual`: Open link = `window.open(url,"_blank","noopener,noreferrer")` rồi `POST /jobs/{id}/opened` (§17.4).
- Chế độ `local_browser` (§32.8): toggle "Tự động mở link", hiển thị trạng thái + countdown "job kế mở sau N giây", nút Pause/Resume/Tắt; frontend **không** gọi `window.open` (backend đã mở), JobPanel phản ánh state qua WS.
- Confirm disable tới hết countdown; Enter **không** = hoàn thành. Frontend security §17.5 (token không vào storage/query).
- **DoD:** frontend tests §22.5 pass.

### Phase 5 — E2E + Pilot — v2.0 §22.6, §24, §25
- E2E flow §22.6 (Skip → verify no claim; Confirm → wait → claim → verify DB/stats/redaction; Stop).
- Nghiệm thu §24 (đủ 4 nhóm checkbox). Pilot đo §25.1, quyết định GO/No-Go §25.2/25.3.

### Phase 6+ — sau pilot (không làm trong MVP)
Reliability (recovery, circuit breaker nâng cao, backup), rồi optional: user auth/hosted multi-user, encrypted TokenStore, ADB opener, reporting, **TikTok analytics bounded context** (§27, có mini-spike riêng).

## 2. Ghi chú thực thi (làm rõ vài điểm của v2.0)

- **`GET /health`**: v2.0 nhắc ở §23.4 nhưng chưa có trong §15 — coi là endpoint chính thức, thêm ở Phase 1.
- **Unique job `(account_id, provider, profile_key, external_id)`** là cross-session: job đã xử lý ở session trước sẽ **không** fetch lại ở session sau; `jobs.session_id` giữ session **đầu tiên** fetch nó. Dedup theo `ON CONFLICT DO NOTHING`.
- **RETRY_WAIT**: retry claim dùng lại `opened_at`/`user_confirmed_at` đã có, **không** yêu cầu mở lại link.
- **Không hard-code hợp đồng API**: mọi `job_field`/`claim_type`/`id_format` đọc từ `config/job_profiles.json` (verified sau spike), profile `enabled=false` cho tới khi GO.
- **Auto-open (§32) KHÔNG vi phạm invariant**: mở một URL đã validate (thủ công hoặc backend local) khác hoàn toàn với auto-click/auto-interaction (bị cấm §3.3). Auto-open **không** auto-confirm, **không** auto-claim; claim vẫn qua `can_claim()` + `USER_CONFIRMED`. Chỉ bật ở `local_browser` + chế độ local; hosted phải fail-closed.

## 3. Quality gate (mọi module) — v2.0 §31.2

Type hints · public contract rõ · validation · unit test · không log secret · timeout mọi I/O · error mapping · không nuốt exception · integration test khi chạm DB/network · không vi phạm state machine invariant.

## 4. Verification tổng thể

1. Phase 0 gate: `GO_NO_GO.md=GO` + parser tests pass.
2. `docker compose up -d` → Postgres; `alembic upgrade head` tạo đủ 6 bảng + index.
3. `pytest` backend: unit §22.1 + parser §22.2 + integration §22.3 + db §22.4 pass.
4. Frontend: Vitest §22.5 pass.
5. E2E §22.6: token không lộ ở network tab lẫn `logs/`; Skip không phát sinh claim; claim ghi đủ `jobs`/`job_attempts`/`api_calls`.

## 5. Ngoài phạm vi (giữ nguyên rào an toàn) — v2.0 §3.3, §28, §29

Không auto-click/UI automation · không OpenCV/CAPTCHA solver · không bypass checkpoint/cookie injection/fingerprint spoof · **không account rotation · không proxy rotation · không anti-detection**. TikTok chỉ dùng API chính thức, read-only.
