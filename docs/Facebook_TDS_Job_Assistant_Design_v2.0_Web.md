# Facebook TDS Job Assistant — Tài liệu thiết kế hệ thống Web

> **Phiên bản:** 2.0 — Web Architecture Alignment  
> **Ngày cập nhật:** 25/07/2026  
> **Trạng thái:** Design specification đồng bộ với `IMPLEMENTATION_PLAN.md`  
> **Kiến trúc:** Vue 3 + TypeScript + FastAPI + PostgreSQL  
> **Mô hình vận hành:** Bán tự động, local-first, sẵn sàng mở rộng multi-user  
> **Nguyên tắc bắt buộc:** Người dùng tự thao tác Facebook và xác nhận thủ công trước khi backend gọi API nhận điểm.

---

## Lịch sử thay đổi

### Phiên bản 2.0

Phiên bản này thay thế định hướng CLI + SQLite của bản 1.1 bằng kiến trúc web app:

- Bỏ CLI làm giao diện chính.
- Dùng Vue 3 + TypeScript cho frontend.
- Dùng FastAPI cho backend.
- Dùng PostgreSQL 16 thay SQLite.
- Dùng SQLAlchemy 2.0 async + asyncpg.
- Dùng Alembic quản lý migration.
- Mở link Facebook ở phía frontend bằng `window.open`.
- Backend là nguồn sự thật cho state machine, min-wait, session limit và claim.
- Thêm WebSocket để cập nhật job, claim result, session stats và log theo thời gian thực.
- Có bảng `accounts` và abstraction `TokenStore` từ đầu.
- MVP vẫn local-first, chưa có login UI.
- Thiết kế không khóa cứng vào một người dùng.
- Tách TikTok channel monitoring thành bounded context độc lập.
- Không đưa auto-click, OpenCV, CAPTCHA solver, proxy rotation hoặc anti-detection vào roadmap.

### Tài liệu nguồn

Bản thiết kế này được đồng bộ từ:

1. `Facebook_TDS_Job_Assistant_Step_By_Step_v1.1.md`
2. `IMPLEMENTATION_PLAN.md`

Khi hai tài liệu cũ mâu thuẫn, `IMPLEMENTATION_PLAN.md` là nguồn quyết định cho kiến trúc triển khai.

---

# Mục lục

1. [Tóm tắt dự án](#1-tóm-tắt-dự-án)
2. [Mục tiêu và kết quả mong muốn](#2-mục-tiêu-và-kết-quả-mong-muốn)
3. [Phạm vi và giới hạn](#3-phạm-vi-và-giới-hạn)
4. [Nguyên tắc kiến trúc](#4-nguyên-tắc-kiến-trúc)
5. [Bounded contexts](#5-bounded-contexts)
6. [Kiến trúc tổng thể](#6-kiến-trúc-tổng-thể)
7. [Cấu trúc monorepo](#7-cấu-trúc-monorepo)
8. [Stack công nghệ](#8-stack-công-nghệ)
9. [Luồng nghiệp vụ](#9-luồng-nghiệp-vụ)
10. [Phase 0 — API Spike](#10-phase-0--api-spike)
11. [Cấu hình hệ thống](#11-cấu-hình-hệ-thống)
12. [Mô hình dữ liệu PostgreSQL](#12-mô-hình-dữ-liệu-postgresql)
13. [State machine](#13-state-machine)
14. [Thiết kế backend FastAPI](#14-thiết-kế-backend-fastapi)
15. [Thiết kế REST API](#15-thiết-kế-rest-api)
16. [Thiết kế WebSocket](#16-thiết-kế-websocket)
17. [Thiết kế frontend Vue 3](#17-thiết-kế-frontend-vue-3)
18. [TokenStore và hướng multi-user](#18-tokenstore-và-hướng-multi-user)
19. [Logging, redaction và quan sát hệ thống](#19-logging-redaction-và-quan-sát-hệ-thống)
20. [Retry, rate limit và circuit breaker](#20-retry-rate-limit-và-circuit-breaker)
21. [Bảo vệ phiên và tài khoản](#21-bảo-vệ-phiên-và-tài-khoản)
22. [Kiểm thử](#22-kiểm-thử)
23. [Chạy local](#23-chạy-local)
24. [Tiêu chí nghiệm thu](#24-tiêu-chí-nghiệm-thu)
25. [Pilot Go/No-Go](#25-pilot-gono-go)
26. [Lộ trình triển khai](#26-lộ-trình-triển-khai)
27. [Mở rộng TikTok channel monitoring](#27-mở-rộng-tiktok-channel-monitoring)
28. [Định hướng tự động hóa tương lai](#28-định-hướng-tự-động-hóa-tương-lai)
29. [Quyết định về proxy và xoay IP](#29-quyết-định-về-proxy-và-xoay-ip)
30. [Checklist bàn giao](#30-checklist-bàn-giao)
31. [Phụ lục](#31-phụ-lục)

---

# 1. Tóm tắt dự án

## 1.1. Tên dự án

**Facebook TDS Job Assistant**

## 1.2. Mô tả ngắn

Đây là một web app hỗ trợ người dùng thực hiện nhiệm vụ Facebook do TraoDoiSub cung cấp.

Luồng chính:

```text
Backend gọi API TDS lấy job
        ↓
Frontend hiển thị job
        ↓
Người dùng mở link Facebook
        ↓
Người dùng tự thao tác trên Facebook
        ↓
Người dùng xác nhận kết quả trong web app
        ↓
Backend kiểm tra state + min-wait + session limit
        ↓
Backend gọi API TDS claim điểm
        ↓
PostgreSQL lưu trạng thái, attempt, API call và thống kê
        ↓
WebSocket cập nhật UI theo thời gian thực
```

## 1.3. Vai trò của hệ thống

Hệ thống tự động hóa phần quản trị workflow:

- Xác thực token TDS phía server.
- Lấy danh sách job.
- Chuẩn hóa job.
- Validate URL.
- Chống job trùng.
- Quản lý state machine.
- Lưu session và job.
- Kiểm tra điều kiện claim.
- Gọi API claim.
- Ghi log đã redaction.
- Cập nhật thống kê realtime.

Hệ thống không tự động hóa hành động tương tác Facebook:

- Không tự Like.
- Không tự Follow.
- Không tự Reaction.
- Không tự Join Group.
- Không tự Comment.
- Không tự xác nhận thay người dùng.

---

# 2. Mục tiêu và kết quả mong muốn

## 2.1. Mục tiêu Phase 0

Xác minh hợp đồng API TDS thật bằng Postman và fixtures.

Kết quả bắt buộc:

- `API_NOTES.md`
- Fixtures đã redaction.
- `parser_prototype.py`
- Parser tests.
- `GO_NO_GO.md`

## 2.2. Mục tiêu MVP web

Web app phải chạy được luồng:

```text
Chọn profile
→ tạo session
→ fetch job thủ công
→ hiển thị job
→ mở link bằng tab mới
→ user báo đã mở
→ user thao tác Facebook
→ user xác nhận hoặc bỏ qua
→ backend claim khi đủ điều kiện
→ lưu PostgreSQL
→ hiển thị stats và log realtime
```

## 2.3. Mục tiêu kiến trúc dài hạn

- Local-first trong giai đoạn đầu.
- Có thể public host sau này.
- Có thể thêm user authentication.
- Có thể quản lý token per-user.
- Có thể thêm nhiều provider/platform.
- Có thể thêm TikTok analytics như module độc lập.
- Không phải viết lại core state machine hoặc database từ đầu khi mở rộng.

---

# 3. Phạm vi và giới hạn

## 3.1. Trong phạm vi MVP

- Vue 3 web UI.
- FastAPI backend.
- PostgreSQL.
- Một local account mặc định.
- Token TDS từ `.env`.
- Một job profile đã được API spike xác minh.
- Manual fetch.
- Manual confirmation.
- Browser link opening từ frontend.
- Claim server-side.
- State machine server-side.
- Session stats.
- WebSocket realtime.
- Structured logging.
- Token redaction.
- Retry có giới hạn.
- HTTP 429 + `Retry-After`.
- Account warning endpoint.
- Unit, integration và E2E test.

## 3.2. Ngoài phạm vi MVP

- Login/register.
- Hosted multi-user production.
- Per-user encrypted credential store.
- ADB opener.
- Desktop app.
- CSV/reporting nâng cao.
- Multi-provider production.
- TikTok analytics implementation.
- Background scheduler quy mô lớn.

## 3.3. Tuyệt đối không triển khai

- Auto-click trên Facebook hoặc TikTok.
- Điều khiển UI để tạo Like/Follow/Reaction/Comment.
- OpenCV nhận diện nút tương tác.
- CAPTCHA solver.
- Bypass checkpoint.
- Cookie injection.
- Giả mạo fingerprint thiết bị.
- Account rotation.
- Proxy rotation nhằm tránh giới hạn hoặc che giấu automation.
- Cơ chế anti-detection.
- Claim khi chưa có xác nhận thủ công.
- Gửi token TDS xuống frontend.

---

# 4. Nguyên tắc kiến trúc

## 4.1. Local-first, multi-user-ready

MVP chạy trên máy cá nhân:

- Backend đọc token từ `.env`.
- Không cần login UI.
- Chỉ có một local account được bootstrap.

Tuy nhiên database và service layer phải sẵn sàng cho nhiều người dùng:

- Có bảng `accounts`.
- `sessions.account_id` bắt buộc.
- `jobs.account_id` bắt buộc.
- Mọi repository query phải scope theo `account_id`.
- Token được truy cập qua `TokenStore`.
- Không đọc trực tiếp `os.getenv()` trong TDS client.

## 4.2. Server-side là source of truth

Frontend không quyết định:

- Job có được claim hay không.
- Min-wait đã đủ hay chưa.
- State transition có hợp lệ không.
- Session đã vượt giới hạn chưa.
- Job có bị trùng không.
- Claim đã thành công hay chưa.

Frontend chỉ:

- Hiển thị dữ liệu.
- Gửi command.
- Mở link client-side.
- Hiển thị countdown hỗ trợ.
- Nhận sự kiện realtime.

## 4.3. Hợp đồng API phải được xác minh

Không viết parser production dựa trên giả định.

Provider TDS chỉ được hoàn thiện sau khi:

- API spike = GO.
- Fixtures đã có.
- Parser prototype pass.
- Field mapping đã được ghi nhận.

## 4.4. Manual confirmation là invariant

Mọi đường dẫn claim đều phải kiểm tra:

```text
job.state == USER_CONFIRMED
```

Frontend không thể bỏ qua invariant này bằng cách gọi endpoint trực tiếp.

## 4.5. Provider và platform là hai khái niệm khác nhau

Ví dụ hiện tại:

```text
provider = "tds"
platform = "facebook"
```

Provider trả job và claim điểm.

Platform xác định:

- Quy tắc URL.
- Cách mở link.
- Cảnh báo vận hành.
- Metadata liên quan.

---

# 5. Bounded contexts

## 5.1. TDS Task Exchange

Đây là bounded context đang triển khai.

Domain:

- Account.
- Job profile.
- Session.
- Job.
- Job attempt.
- Claim.
- API call.
- State transition.

Luồng:

```text
fetch → open → manual action → manual confirm → claim
```

## 5.2. TikTok Channel Monitoring

Đây là bounded context tương lai.

Mục tiêu:

- OAuth 2.0 với API chính thức TikTok for Developers.
- Đọc thông tin kênh.
- Đọc danh sách video khi scope cho phép.
- Poll chỉ số.
- Lưu time-series.
- Hiển thị analytics dashboard.

Không dùng:

- `jobs`
- `job_attempts`
- claim state machine
- TDS token
- manual job confirmation

Bảng tương lai dự kiến:

```text
integration_credentials
tiktok_channels
tiktok_videos
tiktok_metric_snapshots
oauth_states
```

## 5.3. Quy tắc không trộn context

Không thêm field TikTok analytics vào bảng `jobs`.

Không dùng `ClaimService` cho TikTok analytics.

Không dùng TDS account token để gọi TikTok API.

Không đặt TikTok OAuth token trong `job_profiles.json`.

---

# 6. Kiến trúc tổng thể

## 6.1. Sơ đồ logic

```text
┌───────────────────────────────────────────────────────────┐
│                    Browser — Vue 3                        │
│ Dashboard / Session / Job / Stats / Log                  │
└──────────────────────┬───────────────────────┬────────────┘
                       │ REST                  │ WebSocket
                       ▼                       ▼
┌───────────────────────────────────────────────────────────┐
│                    FastAPI Backend                        │
│                                                           │
│ Routes → Services → State Machine → Repositories          │
│              │                  │                         │
│              ▼                  ▼                         │
│       TDS Provider Client      PostgreSQL                 │
│              │                                            │
│              ▼                                            │
│         TraoDoiSub API                                    │
└───────────────────────────────────────────────────────────┘

Frontend Open Link
        │
        ▼
Facebook tab/window
        │
        ▼
Người dùng thao tác thủ công
```

## 6.2. Trust boundaries

### Frontend không đáng tin cậy

Backend phải validate lại mọi input:

- Session ID.
- Job ID.
- Command.
- State hiện tại.
- Account ownership.
- Min-wait.
- Claim eligibility.

### TDS response không đáng tin cậy

Backend phải:

- Validate JSON.
- Parse bằng model.
- Giữ raw payload đã redaction.
- Không coi HTTP 200 là nghiệp vụ thành công.
- Phân biệt auth error, no jobs và business error.

### Database là nguồn lưu trạng thái bền vững

Queue trong memory chỉ là cache.

State thật nằm trong PostgreSQL.

---

# 7. Cấu trúc monorepo

```text
facebook-tool/
├── docker-compose.yml
├── README.md
├── .gitignore
├── docs/
│   ├── Facebook_TDS_Job_Assistant_Design_v2.0_Web.md
│   └── IMPLEMENTATION_PLAN.md
│
├── backend/
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── .env.example
│   ├── alembic.ini
│   │
│   ├── api_spike/
│   │   ├── API_NOTES.md
│   │   ├── sanitized_requests/
│   │   ├── sanitized_responses/
│   │   ├── fixtures/
│   │   ├── parser_prototype.py
│   │   └── GO_NO_GO.md
│   │
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   │
│   │   ├── config/
│   │   │   └── settings.py
│   │   │
│   │   ├── core/
│   │   │   ├── logging.py
│   │   │   ├── redaction.py
│   │   │   └── security/
│   │   │       └── token_store.py
│   │   │
│   │   ├── db/
│   │   │   ├── session.py
│   │   │   ├── models.py
│   │   │   ├── repositories/
│   │   │   └── migrations/
│   │   │
│   │   ├── schemas/
│   │   │   ├── account.py
│   │   │   ├── profile.py
│   │   │   ├── session.py
│   │   │   ├── job.py
│   │   │   ├── claim.py
│   │   │   └── events.py
│   │   │
│   │   ├── providers/
│   │   │   └── tds/
│   │   │       ├── client.py
│   │   │       ├── parser.py
│   │   │       ├── models.py
│   │   │       └── errors.py
│   │   │
│   │   ├── platforms/
│   │   │   └── facebook/
│   │   │       ├── rules.py
│   │   │       └── urls.py
│   │   │
│   │   ├── jobs/
│   │   │   ├── service.py
│   │   │   ├── state_machine.py
│   │   │   └── filters.py
│   │   │
│   │   ├── claims/
│   │   │   └── service.py
│   │   │
│   │   ├── sessions/
│   │   │   └── service.py
│   │   │
│   │   ├── api/
│   │   │   └── routes/
│   │   │       ├── profile.py
│   │   │       ├── profiles.py
│   │   │       ├── sessions.py
│   │   │       ├── jobs.py
│   │   │       ├── claims.py
│   │   │       └── ws.py
│   │   │
│   │   └── ws/
│   │       └── manager.py
│   │
│   └── tests/
│       ├── unit/
│       ├── integration/
│       ├── fixtures/
│       └── conftest.py
│
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    ├── .env.example
    └── src/
        ├── main.ts
        ├── App.vue
        ├── router/
        ├── api/
        ├── stores/
        ├── types/
        ├── views/
        │   ├── Dashboard.vue
        │   └── SessionView.vue
        └── components/
            ├── AccountCard.vue
            ├── ProfileSelector.vue
            ├── JobPanel.vue
            ├── ConfirmBar.vue
            ├── SessionStats.vue
            └── LogPanel.vue
```

---

# 8. Stack công nghệ

## 8.1. Backend

- Python 3.11+
- FastAPI
- Uvicorn
- Pydantic v2
- pydantic-settings
- SQLAlchemy 2.0 async
- asyncpg
- Alembic
- httpx
- tenacity
- structlog hoặc logging JSON formatter

## 8.2. Backend testing

- pytest
- pytest-asyncio
- respx
- httpx AsyncClient
- testcontainers tùy chọn
- PostgreSQL test database

## 8.3. Frontend

- Vue 3
- Composition API
- TypeScript
- Vite
- Pinia
- Vue Router
- Axios
- Native WebSocket API hoặc wrapper mỏng

## 8.4. Frontend testing đề xuất

- Vitest
- Vue Test Utils
- Playwright cho E2E

## 8.5. Database

- PostgreSQL 16
- JSONB cho payload API
- TIMESTAMPTZ cho timestamp
- UUID cho domain entity
- BIGINT identity cho append-only log tables

---

# 9. Luồng nghiệp vụ

## 9.1. Khởi động backend

```text
Load settings
→ validate safety invariants
→ connect PostgreSQL
→ run health check
→ initialize TokenStore
→ bootstrap local account
→ load verified job profiles
→ start FastAPI
```

Nếu một invariant quan trọng sai, backend fail-fast.

## 9.2. Khởi động frontend

```text
Load app
→ GET account profile
→ GET job profiles
→ render dashboard
```

Frontend không nhận token TDS.

## 9.3. Tạo session

```text
User chọn profile
→ POST /api/sessions
→ backend kiểm tra profile enabled
→ backend tạo session RUNNING
→ frontend kết nối WebSocket
→ chuyển sang SessionView
```

## 9.4. Fetch job

```text
User nhấn Fetch
→ POST /api/sessions/{id}/fetch
→ backend kiểm tra session limit
→ TDS client gọi get-jobs
→ parser normalize
→ URL validator kiểm tra
→ repository chống trùng
→ job state = FETCHED/VALIDATED
→ WebSocket job.created
```

MVP không tự động poll.

## 9.5. Mở link

```text
User nhấn Open link
→ frontend window.open(job.url)
→ nếu browser chấp nhận mở:
   POST /api/jobs/{id}/opened
→ backend transition OPENING → OPENED → WAITING_USER
→ lưu opened_at theo giờ server
```

`window.open()` không chứng minh trang Facebook đã tải hoặc hành động đã hoàn tất.

## 9.6. Xác nhận thủ công

User có thể chọn:

- Hoàn thành.
- Bỏ qua.
- Link không hợp lệ.
- Báo checkpoint/cảnh báo.
- Dừng session.

Khi chọn hoàn thành:

```text
POST /api/jobs/{id}/confirm
→ backend kiểm tra state
→ transition USER_CONFIRMED
```

## 9.7. Claim

```text
POST /api/jobs/{id}/claim
→ ClaimService.can_claim()
→ kiểm tra manual confirmation
→ kiểm tra min-wait từ opened_at
→ kiểm tra chưa claim
→ kiểm tra session còn RUNNING
→ kiểm tra account không protection-stop
→ transition CLAIM_PENDING → CLAIMING
→ gọi TDS API
→ parse result
→ update state
→ ghi attempt + api_calls
→ publish WebSocket event
```

## 9.8. Dừng phiên

Session dừng khi:

- User nhấn Stop.
- Đạt max jobs.
- Đạt max duration.
- User báo checkpoint.
- User báo temporary block.
- Token invalid.
- Circuit breaker mở và operator chọn stop.
- Backend shutdown.

---

# 10. Phase 0 — API Spike

## 10.1. Mục tiêu

Xác minh hợp đồng API TDS trước khi hoàn thiện provider production.

## 10.2. Cấu trúc

```text
backend/api_spike/
├── API_NOTES.md
├── sanitized_requests/
├── sanitized_responses/
├── fixtures/
├── parser_prototype.py
└── GO_NO_GO.md
```

## 10.3. Kiểm tra profile

Ghi lại:

- HTTP method.
- URL.
- Query params.
- Headers.
- Response token thật.
- Response token sai.
- Username field.
- Balance field.
- Status code.
- Content-Type.

## 10.4. Kiểm tra get-jobs

Chỉ chọn một job type cho MVP.

Ghi lại:

- `fields` thật.
- External ID field.
- URL field.
- Action field nếu có.
- Response có job.
- Response hết job.
- Response account chưa cấu hình.
- Response rate limit nếu gặp.

## 10.5. Kiểm tra claim

Thực hiện job thủ công, sau đó kiểm tra:

- Claim method.
- Claim URL.
- `type` thật.
- ID đơn hay list.
- Min-wait.
- Success response.
- Too-fast response.
- Rejected response.
- Auth error.
- Balance update.

## 10.6. Fixtures tối thiểu

```text
profile_success.json
profile_invalid_token.json
jobs_success.json
jobs_empty.json
jobs_account_not_configured.json
claim_success.json
claim_too_fast.json
claim_rejected.json
claim_auth_error.json
```

## 10.7. Parser prototype

Parser prototype phải:

- Không gọi network.
- Đọc fixtures.
- Parse profile.
- Parse jobs.
- Parse claim.
- Phân biệt no-jobs với auth error.
- Fail rõ khi response không xác định.
- Không chứa token thật.

## 10.8. Điều kiện GO

- Profile thật hoạt động.
- Token sai được nhận diện.
- Có job thật.
- Xác định được ID và URL.
- Claim thủ công thành công.
- Xác định được claim type.
- Xác định được ID format.
- Fixtures đầy đủ.
- Parser tests pass.
- Không cần cookie Facebook.
- Không cần CAPTCHA hoặc bypass để gọi API.
- Không có unknown chặn MVP.

## 10.9. Điều kiện NO-GO

- Không xác định được endpoint.
- Claim không hoạt động.
- Response không thể phân biệt.
- API yêu cầu cơ chế ngoài phạm vi.
- Cần gửi credential Facebook.
- Không thể redaction.
- Rate limit làm workflow không khả thi.
- Parser phụ thuộc text ngẫu nhiên không ổn định.

---

# 11. Cấu hình hệ thống

## 11.1. `.env.example` backend

```dotenv
APP_ENV=development
APP_NAME=Facebook TDS Job Assistant
LOG_LEVEL=INFO

DATABASE_URL=postgresql+asyncpg://tds:tds@localhost:5432/tds_assistant

CORS_ORIGINS=http://localhost:5173

TDS_BASE_URL=https://traodoisub.com/api/
TDS_ACCESS_TOKEN=replace_me
TDS_REQUEST_TIMEOUT_SECONDS=15
TDS_MAX_RETRIES=3

FETCH_MODE=manual
AUTO_POLL_ENABLED=false

MIN_SECONDS_BEFORE_CONFIRM=2
MIN_SECONDS_BEFORE_CLAIM=3
MAX_JOBS_PER_SESSION=20
MAX_SESSION_DURATION_MINUTES=30

REQUIRE_MANUAL_CONFIRMATION=true
AUTO_CLAIM_WITHOUT_CONFIRMATION=false

HONOR_RETRY_AFTER=true
STOP_ON_FACEBOOK_WARNING=true
STOP_ON_CHECKPOINT=true
STOP_ON_TEMPORARY_BLOCK=true
STOP_ON_IDENTITY_VERIFICATION=true
```

Các số giới hạn trên là mặc định vận hành của ứng dụng, không phải ngưỡng bảo đảm an toàn tài khoản.

## 11.2. Validation bắt buộc

Backend không khởi động nếu:

- Token rỗng.
- TDS base URL không dùng HTTPS.
- Timeout <= 0.
- Retry ngoài 0–5.
- `FETCH_MODE != manual` trong MVP.
- Auto-poll bật.
- Max jobs <= 0.
- Max duration <= 0.
- Manual confirmation tắt.
- Auto claim bật.
- `HONOR_RETRY_AFTER=false`.
- Một cờ STOP_ON_* bị tắt.
- DATABASE_URL không parse được.
- CORS origins không hợp lệ.

## 11.3. Job profile config

```json
{
  "version": 1,
  "profiles": [
    {
      "key": "facebook_verified_profile",
      "display_name": "Facebook Verified Job Type",
      "provider": "tds",
      "platform": "facebook",
      "job_method": "FILL_FROM_SPIKE",
      "job_field": "FILL_FROM_SPIKE",
      "claim_method": "FILL_FROM_SPIKE",
      "claim_type": "FILL_FROM_SPIKE",
      "id_format": "FILL_FROM_SPIKE",
      "minimum_claim_wait_seconds": 3,
      "enabled": false,
      "verified_at": null,
      "fixture_version": null
    }
  ]
}
```

Profile chỉ được bật khi API spike = GO.

---

# 12. Mô hình dữ liệu PostgreSQL

## 12.1. `accounts`

Mục đích:

- Đại diện chủ thể sở hữu session và credential.
- Chuẩn bị cho multi-user.

Trường đề xuất:

```text
id UUID PK
display_name VARCHAR
status VARCHAR
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

MVP bootstrap một account:

```text
display_name = "Local User"
status = "ACTIVE"
```

## 12.2. `sessions`

```text
id UUID PK
account_id UUID FK accounts
profile_key VARCHAR
provider VARCHAR
platform VARCHAR
status VARCHAR
started_at TIMESTAMPTZ
ended_at TIMESTAMPTZ NULL
stop_reason VARCHAR NULL
jobs_fetched INTEGER
jobs_opened INTEGER
jobs_confirmed INTEGER
jobs_claimed INTEGER
jobs_failed INTEGER
points_earned BIGINT
max_jobs INTEGER
max_duration_minutes INTEGER
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

## 12.3. `jobs`

```text
id UUID PK
account_id UUID FK accounts
session_id UUID FK sessions
external_id VARCHAR
profile_key VARCHAR
provider VARCHAR
platform VARCHAR
job_field VARCHAR
claim_type VARCHAR
url TEXT
action_label VARCHAR NULL
state VARCHAR
fetched_at TIMESTAMPTZ
opened_at TIMESTAMPTZ NULL
user_confirmed_at TIMESTAMPTZ NULL
claimed_at TIMESTAMPTZ NULL
last_error_code VARCHAR NULL
last_error_message TEXT NULL
raw_job_json JSONB
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

Unique đề xuất:

```text
UNIQUE(account_id, provider, profile_key, external_id)
```

Không dùng unique chỉ theo external ID nếu nhiều provider có thể trùng namespace.

## 12.4. `job_attempts`

```text
id BIGINT IDENTITY PK
job_id UUID FK jobs
session_id UUID FK sessions
account_id UUID FK accounts
attempt_type VARCHAR
started_at TIMESTAMPTZ
ended_at TIMESTAMPTZ NULL
success BOOLEAN
error_code VARCHAR NULL
error_message TEXT NULL
response_json JSONB NULL
created_at TIMESTAMPTZ
```

## 12.5. `api_calls`

```text
id BIGINT IDENTITY PK
account_id UUID FK accounts
session_id UUID NULL
job_id UUID NULL
provider VARCHAR
operation VARCHAR
method VARCHAR
url_redacted TEXT
status_code INTEGER NULL
duration_ms INTEGER NULL
success BOOLEAN
error_code VARCHAR NULL
response_json JSONB NULL
retry_after_seconds INTEGER NULL
created_at TIMESTAMPTZ
```

## 12.6. `app_state`

```text
id BIGINT IDENTITY PK
account_id UUID FK accounts
key VARCHAR
value_json JSONB
updated_at TIMESTAMPTZ
UNIQUE(account_id, key)
```

## 12.7. Index

```sql
CREATE INDEX idx_sessions_account_status
ON sessions(account_id, status);

CREATE INDEX idx_jobs_account_state
ON jobs(account_id, state);

CREATE INDEX idx_jobs_session_state
ON jobs(session_id, state);

CREATE INDEX idx_jobs_fetched_at
ON jobs(fetched_at DESC);

CREATE INDEX idx_attempts_job
ON job_attempts(job_id, created_at DESC);

CREATE INDEX idx_api_calls_account_created
ON api_calls(account_id, created_at DESC);
```

## 12.8. Transaction boundaries

Không giữ transaction mở trong lúc:

- Chờ người dùng.
- Gọi TDS API.
- Gửi WebSocket.
- Mở link.

Quy trình claim:

1. Transaction ngắn: lock job và validate state.
2. Commit state `CLAIMING`.
3. Gọi API ngoài transaction.
4. Transaction ngắn: lưu result và state cuối.
5. Publish event.

Cần dùng optimistic locking hoặc row-level lock để chống double claim.

## 12.9. Migration

Migration đầu tiên:

```text
0001_init_accounts_sessions_jobs_attempts_api_calls_app_state
```

Mọi thay đổi schema sau đó phải qua Alembic.

Không dùng `create_all()` thay migration trong production path.

---

# 13. State machine

## 13.1. Job states

```text
FETCHED
VALIDATED
OPENING
OPENED
WAITING_USER
USER_CONFIRMED
USER_SKIPPED
LINK_INVALID
OPEN_FAILED
CLAIM_PENDING
CLAIMING
CLAIMED
CLAIM_REJECTED
RETRY_WAIT
AUTH_FAILED
ACCOUNT_PROTECTION_STOP
CANCELLED
```

## 13.2. Transition hợp lệ

| From | To | Điều kiện |
|---|---|---|
| FETCHED | VALIDATED | ID và URL hợp lệ |
| FETCHED | LINK_INVALID | URL không hợp lệ |
| VALIDATED | OPENING | Frontend yêu cầu mở |
| OPENING | OPENED | Frontend báo đã gọi `window.open` |
| OPENED | WAITING_USER | Backend ghi `opened_at` |
| WAITING_USER | USER_CONFIRMED | User xác nhận |
| WAITING_USER | USER_SKIPPED | User bỏ qua |
| WAITING_USER | LINK_INVALID | User báo link lỗi |
| USER_CONFIRMED | CLAIM_PENDING | `can_claim` pass |
| CLAIM_PENDING | CLAIMING | Bắt đầu claim |
| CLAIMING | CLAIMED | TDS success |
| CLAIMING | RETRY_WAIT | Lỗi tạm thời |
| CLAIMING | CLAIM_REJECTED | Lỗi vĩnh viễn |
| RETRY_WAIT | CLAIMING | Retry hợp lệ |
| Any active | ACCOUNT_PROTECTION_STOP | User báo warning |
| Any non-terminal | CANCELLED | Dừng session |

## 13.3. Transition bị cấm

- FETCHED → CLAIMED.
- OPENED → CLAIMING.
- WAITING_USER → CLAIMING.
- USER_SKIPPED → CLAIMING.
- LINK_INVALID → CLAIMING.
- CLAIMED → CLAIMING.
- CANCELLED → CLAIMING.
- ACCOUNT_PROTECTION_STOP → CLAIMING.

## 13.4. Concurrency

`transition()` phải:

- Đọc state hiện tại trong transaction.
- So sánh expected state.
- Update theo điều kiện.
- Báo `409 Conflict` nếu state đã thay đổi.

---

# 14. Thiết kế backend FastAPI

## 14.1. `app/main.py`

Trách nhiệm:

- Tạo FastAPI app.
- Cấu hình CORS.
- Include routers.
- Startup/shutdown lifecycle.
- Database health check.
- Initialize services.
- WebSocket route.
- Exception handlers.
- Request ID middleware.

## 14.2. Settings

Dùng `pydantic-settings`.

Không đọc `.env` trực tiếp trong module khác.

Settings groups:

```text
AppSettings
DatabaseSettings
TDSSettings
WorkflowSettings
SafetySettings
CorsSettings
```

## 14.3. Logging

- JSON logs.
- ISO 8601.
- Request ID.
- Account ID.
- Session ID.
- Job ID.
- Event name.
- Duration.
- Redaction trước serialization.

## 14.4. Token store

Interface:

```python
class TokenStore(Protocol):
    async def get_token(
        self,
        account_id: UUID,
        credential_type: str,
    ) -> str:
        ...
```

MVP:

```text
LocalEnvTokenStore
```

Tương lai:

```text
EncryptedDatabaseTokenStore
OAuthTokenStore
ExternalSecretsManagerTokenStore
```

## 14.5. Database session

- Async engine.
- Async session maker.
- Dependency per request.
- Rollback khi exception.
- Pool settings phù hợp local.

## 14.6. TDS provider client

Dùng `httpx.AsyncClient`.

Request wrapper xử lý:

- Timeout.
- DNS/network.
- TLS.
- Non-2xx.
- HTML body.
- Invalid JSON.
- Empty JSON.
- HTTP 429.
- Retry-After.
- Redaction.
- API call persistence.

## 14.7. Parser

Parser không gọi network.

Input:

```text
status_code
headers
json/body
verified profile mapping
```

Output:

```text
TDSProfileResult
TDSJobsResult
TDSClaimResult
```

## 14.8. Jobs service

Trách nhiệm:

- Fetch.
- Normalize.
- Validate.
- Deduplicate.
- Save.
- Select next job.
- Publish event.

## 14.9. Claim service

`can_claim(job)` kiểm tra:

```text
state == USER_CONFIRMED
external_id exists
claim_type exists
opened_at exists
user_confirmed_at exists
min-wait elapsed by server time
not already claimed
session status == RUNNING
account not protection-stopped
session limits not exceeded
```

## 14.10. Session service

- Create session.
- Stop session.
- Enforce limits.
- Update counters.
- Calculate summary.
- Mark protection stop.
- Recover interrupted sessions.

---

# 15. Thiết kế REST API

## 15.1. Quy ước chung

Base path:

```text
/api
```

Response error chuẩn:

```json
{
  "error": {
    "code": "JOB_INVALID_STATE",
    "message": "Job cannot be confirmed from current state",
    "request_id": "uuid",
    "details": {}
  }
}
```

## 15.2. Account profile

```http
GET /api/account/profile
```

Response:

```json
{
  "account_id": "uuid",
  "display_name": "Local User",
  "tds": {
    "username": "example",
    "balance": 12345,
    "status": "VALID"
  }
}
```

Token không xuất hiện trong response.

## 15.3. Job profiles

```http
GET /api/profiles
```

Chỉ trả profile enabled và verified.

## 15.4. Tạo session

```http
POST /api/sessions
```

Request:

```json
{
  "profile_key": "facebook_verified_profile"
}
```

Response:

```json
{
  "id": "uuid",
  "status": "RUNNING",
  "profile_key": "facebook_verified_profile",
  "started_at": "2026-07-25T10:00:00+07:00",
  "limits": {
    "max_jobs": 20,
    "max_duration_minutes": 30
  }
}
```

## 15.5. Stop session

```http
POST /api/sessions/{session_id}/stop
```

Request:

```json
{
  "reason": "USER_REQUESTED"
}
```

## 15.6. Session summary

```http
GET /api/sessions/{session_id}/summary
```

## 15.7. Manual fetch

```http
POST /api/sessions/{session_id}/fetch
```

Backend từ chối nếu:

- Session không chạy.
- Đang có job WAITING_USER.
- Đã đạt giới hạn.
- Account protection stop.
- Circuit breaker mở.

## 15.8. Opened

```http
POST /api/jobs/{job_id}/opened
```

Frontend gọi sau `window.open`.

Backend ghi giờ server.

## 15.9. Confirm

```http
POST /api/jobs/{job_id}/confirm
```

Chỉ chuyển `WAITING_USER → USER_CONFIRMED`.

## 15.10. Skip

```http
POST /api/jobs/{job_id}/skip
```

Request có optional reason.

## 15.11. Invalid link

```http
POST /api/jobs/{job_id}/invalid
```

## 15.12. Claim

```http
POST /api/jobs/{job_id}/claim
```

Response:

```json
{
  "job_id": "uuid",
  "status": "CLAIMED",
  "points_added": 600,
  "balance_after": 12345,
  "message": "Claim successful"
}
```

## 15.13. Account warning

```http
POST /api/sessions/{session_id}/account-warning
```

Request:

```json
{
  "warning_type": "CHECKPOINT",
  "note": "Facebook displayed a checkpoint"
}
```

Backend:

- Dừng session.
- Mark protection stop.
- Không fetch.
- Không claim job chưa hoàn tất.
- Publish event.

---

# 16. Thiết kế WebSocket

## 16.1. Endpoint

```text
/ws/sessions/{session_id}
```

## 16.2. Event envelope

```json
{
  "event": "job.state_changed",
  "timestamp": "2026-07-25T10:10:00+07:00",
  "session_id": "uuid",
  "data": {}
}
```

## 16.3. Event types

```text
session.started
session.updated
session.stopped
job.created
job.state_changed
job.claim_started
job.claim_succeeded
job.claim_failed
account.warning
api.rate_limited
log.event
```

## 16.4. Không gửi qua WebSocket

- Token.
- Cookie.
- Raw Authorization.
- Full sensitive URL query.
- Unredacted API response.

## 16.5. Reconnect

Frontend khi reconnect phải:

1. Reconnect WebSocket.
2. Fetch current session summary.
3. Fetch current job state.
4. Không dựa vào event cũ bị mất.

WebSocket không thay database.

---

# 17. Thiết kế frontend Vue 3

## 17.1. Routes

```text
/                  Dashboard
/sessions/:id      SessionView
```

## 17.2. Pinia stores

### Account store

- profile.
- balance.
- loading.
- error.

### Session store

- current session.
- counters.
- limits.
- status.
- stop reason.

### Job store

- current job.
- queue.
- state.
- min-wait countdown.
- claim result.

### Log store

- realtime events.
- capped history.
- filters.

## 17.3. Dashboard

Components:

- AccountCard.
- ProfileSelector.
- Start Session button.
- Backend health indicator.
- API readiness indicator.

## 17.4. SessionView

### JobPanel

Hiển thị:

- Job ID.
- Profile.
- URL.
- State.
- Fetched time.
- Opened time.
- Action label.

Open link:

```typescript
const openedWindow = window.open(job.url, "_blank", "noopener,noreferrer");

if (openedWindow) {
  await api.markOpened(job.id);
}
```

Không tự click trong tab Facebook.

### ConfirmBar

Buttons:

- Hoàn thành.
- Mở lại.
- Bỏ qua.
- Link lỗi.
- Báo cảnh báo.
- Dừng phiên.

Không map phím Enter thành hoàn thành.

### Countdown

Frontend countdown chỉ hỗ trợ UX.

Backend vẫn kiểm tra min-wait.

### SessionStats

- fetched.
- opened.
- confirmed.
- claimed.
- failed.
- points.
- claim success rate.
- elapsed duration.
- remaining session capacity.

### LogPanel

Nhận event đã redaction.

Không hiển thị raw token.

## 17.5. Frontend security

- Không lưu TDS token.
- Không đưa token vào localStorage/sessionStorage.
- Không truyền token trong query.
- Chỉ gọi backend same-origin hoặc configured API origin.
- Sanitize URL display.
- Dùng `noopener,noreferrer`.

---

# 18. TokenStore và hướng multi-user

## 18.1. MVP local

Bảng `accounts` có một account.

`LocalEnvTokenStore` trả token từ `.env` cho account đó.

## 18.2. Hosted multi-user tương lai

Cần thêm:

- User authentication.
- Authorization.
- Account ownership.
- Credential encryption.
- Key rotation.
- Audit log.
- CSRF/CORS hardening.
- Rate limit per user.
- Tenant isolation.

## 18.3. Credential model tương lai

```text
credentials
- id
- account_id
- provider
- credential_type
- encrypted_payload
- expires_at
- refresh_metadata
- created_at
- updated_at
```

## 18.4. TikTok OAuth compatibility

TokenStore abstraction phải hỗ trợ:

- Static token TDS.
- OAuth access token.
- OAuth refresh token.
- Token expiry.
- Refresh flow.

Không cần implement trong MVP.

---

# 19. Logging, redaction và quan sát hệ thống

## 19.1. Event fields

```text
timestamp
level
event
request_id
account_id
session_id
job_id
provider
platform
duration_ms
status
error_code
```

## 19.2. Redaction targets

- `access_token`
- `Authorization`
- `Cookie`
- `Set-Cookie`
- OAuth code.
- Refresh token.
- Client secret.
- Sensitive query params.

## 19.3. API call persistence

`api_calls` lưu:

- Operation.
- Redacted URL.
- Status.
- Duration.
- Success.
- Error code.
- Redacted response.

## 19.4. Metrics MVP

- API success/error count.
- Claim success rate.
- Duplicate count.
- Parser error count.
- Rate limit count.
- WebSocket client count.
- Session duration.
- Average time per job.

---

# 20. Retry, rate limit và circuit breaker

## 20.1. Retry được phép

- Connection timeout.
- Read timeout.
- Temporary DNS error.
- HTTP 502.
- HTTP 503.
- HTTP 504.

## 20.2. Không retry tự động

- Invalid token.
- Invalid job.
- Claim rejected.
- Account not configured.
- Invalid response mapping.
- HTTP 429 nếu chưa đến `Retry-After`.
- User skip.
- Protection stop.

## 20.3. Retry policy

Ví dụ:

```text
attempt 1 → 2 seconds
attempt 2 → 4 seconds
attempt 3 → fail to workflow
```

Retry chỉ áp dụng lỗi mạng tạm thời.

## 20.4. HTTP 429

Khi nhận 429:

- Parse `Retry-After`.
- Ghi api_calls.
- Mở circuit breaker.
- Publish `api.rate_limited`.
- Không fetch/claim cho đến thời điểm hợp lệ.
- Không đổi account/token/IP để tiếp tục.

## 20.5. Circuit breaker

States:

```text
CLOSED
OPEN
HALF_OPEN
```

MVP có thể dùng implementation đơn giản trong memory nhưng phải persist thời điểm open vào `app_state` để restart không làm mất giới hạn.

---

# 21. Bảo vệ phiên và tài khoản

## 21.1. Session limits

Bắt buộc:

- Max jobs.
- Max duration.
- Chỉ một job WAITING_USER tại một thời điểm cho mỗi session.
- Không fetch khi session stopped.

## 21.2. Warning types

```text
CHECKPOINT
TEMPORARY_BLOCK
IDENTITY_VERIFICATION
FEATURE_UNAVAILABLE
SUSPICIOUS_ACTIVITY
OTHER
```

## 21.3. Khi user báo warning

- Stop session.
- Ghi stop reason.
- Transition active job nếu cần.
- Không mở job mới.
- Không claim job chưa confirm.
- Hiển thị hướng dẫn xử lý qua giao diện chính thức.
- Không hướng dẫn bypass.

## 21.4. Không có “ngưỡng an toàn”

Mọi giới hạn số job trong cấu hình là guardrail của ứng dụng.

Chúng không phải cam kết rằng tài khoản sẽ không bị giới hạn.

---

# 22. Kiểm thử

## 22.1. Backend unit tests

### Settings

- Missing token.
- HTTP base URL.
- Invalid retry.
- Auto-poll true.
- Auto-claim true.
- Manual confirmation false.
- Missing finite session limits.
- STOP_ON_* false.

### Redaction

- Query token.
- Authorization.
- Cookie.
- OAuth token.
- Nested JSON secrets.

### URL validation

- Facebook HTTPS valid.
- Non-Facebook host invalid.
- javascript invalid.
- file invalid.
- empty invalid.
- malformed invalid.

### State machine

- Valid transitions.
- Invalid transitions.
- Claimed cannot claim again.
- Skipped cannot claim.
- Protection stop blocks claim.

### Claim eligibility

- No opened_at.
- No confirmation.
- Min-wait not elapsed.
- Session stopped.
- Already claimed.
- Valid claim.

## 22.2. Provider parser tests

Fixtures từ spike:

- Profile success.
- Invalid token.
- Jobs success.
- Jobs empty.
- Claim success.
- Too fast.
- Rejected.
- HTML body.
- Unknown JSON.

## 22.3. Integration tests

Dùng respx:

- Timeout then success.
- 503 x3.
- 429 + Retry-After.
- Claim success writes DB.
- Duplicate job conflict ignored.
- Two simultaneous claim requests: chỉ một request tới TDS.
- WebSocket receives state event.

## 22.4. Database tests

- Alembic upgrade.
- FK enforcement.
- Unique job.
- Session account scope.
- Rollback.
- Summary counters.

## 22.5. Frontend tests

- Dashboard load.
- Start session.
- Fetch.
- Open link handler.
- Confirm disabled before countdown.
- Skip does not claim.
- Warning stops UI.
- WebSocket reconnect.

## 22.6. E2E

```text
Start Postgres
Start backend
Start frontend
Load profile
Start session
Fetch
Open link
Skip → verify no claim
Fetch another
Open
Confirm
Wait
Claim
Verify DB
Verify stats
Verify log redaction
Stop session
```

---

# 23. Chạy local

## 23.1. Docker Compose PostgreSQL

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: tds
      POSTGRES_PASSWORD: tds
      POSTGRES_DB: tds_assistant
    ports:
      - "5432:5432"
    volumes:
      - tds_postgres_data:/var/lib/postgresql/data

volumes:
  tds_postgres_data:
```

## 23.2. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Windows:

```powershell
cd backend
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

## 23.3. Frontend

```bash
cd frontend
npm install
npm run dev
```

## 23.4. Health checks

```text
Backend: /health
Frontend: http://localhost:5173
PostgreSQL: docker compose ps
```

---

# 24. Tiêu chí nghiệm thu

## 24.1. Phase 0

- [ ] GO_NO_GO = GO.
- [ ] Fixtures đầy đủ.
- [ ] Parser prototype pass.
- [ ] Token đã redaction.
- [ ] Claim thật đã được xác minh thủ công.

## 24.2. Backend

- [ ] Settings fail-fast.
- [ ] Postgres migration chạy.
- [ ] TDS token không rời server.
- [ ] State machine enforce.
- [ ] Manual confirmation enforce.
- [ ] Min-wait server-side.
- [ ] Duplicate claim bị chặn.
- [ ] HTTP 429 được xử lý.
- [ ] Logging redaction pass.
- [ ] WebSocket events hoạt động.

## 24.3. Frontend

- [ ] Dashboard hoạt động.
- [ ] Profile selector.
- [ ] Start/stop session.
- [ ] Manual fetch.
- [ ] Open link client-side.
- [ ] Confirm/skip/invalid.
- [ ] Countdown.
- [ ] Session stats.
- [ ] Log realtime.
- [ ] Warning button.

## 24.4. Security

- [ ] Token không xuất hiện network tab.
- [ ] Token không xuất hiện log.
- [ ] CORS giới hạn.
- [ ] URL validate.
- [ ] No shell command.
- [ ] No auto-click.
- [ ] No proxy rotation.
- [ ] No CAPTCHA bypass.

---

# 25. Pilot Go/No-Go

## 25.1. Pilot đo gì

- API stability.
- Parser stability.
- Claim success rate.
- TDS error rate.
- HTTP 429 count.
- Facebook warning count.
- Time per job.
- Points recorded.
- Maintenance time.
- User experience.

## 25.2. GO

- API mapping ổn định.
- Parser không phải sửa liên tục.
- Claim success đạt ngưỡng dự án đặt trước.
- Không có account warning nghiêm trọng trong pilot.
- Giá trị vận hành hợp lý.
- Không cần cơ chế ngoài phạm vi.

## 25.3. NO-GO

- API liên tục thay đổi.
- Claim thường xuyên thất bại.
- Nhiều rate limit.
- Có checkpoint/block.
- Maintenance cost quá cao.
- Muốn mở rộng phải thêm anti-detection hoặc credential automation.

Pilot không chứng minh an toàn dài hạn.

---

# 26. Lộ trình triển khai

## Phase 0 — API Spike

- Postman.
- Fixtures.
- Parser.
- GO/No-Go.

## Phase 1 — Backend-independent core

Có thể làm song song với spike:

- Monorepo bootstrap.
- Settings.
- PostgreSQL.
- Alembic.
- Models.
- State machine.
- URL validation.
- Redaction.
- TokenStore interface.

## Phase 2 — TDS provider sau GO

- Client.
- Parser.
- Errors.
- API call repository.
- 429 handling.

## Phase 3 — Services và REST

- Sessions.
- Jobs.
- Claims.
- Routes.
- WebSocket.

## Phase 4 — Vue frontend

- Dashboard.
- SessionView.
- Stores.
- API client.
- WebSocket.
- Components.

## Phase 5 — E2E và pilot

- Full flow.
- Database verification.
- Redaction.
- Pilot metrics.
- Go/No-Go.

## Phase 6 — Reliability

- Recovery.
- Better circuit breaker.
- Observability.
- Backups.
- Deployment hardening.

## Phase 7 — Optional future work

- User auth.
- Hosted multi-user.
- Encrypted token store.
- ADB opener chỉ để mở link nếu thực sự cần.
- Advanced reporting.
- TikTok analytics bounded context.

---

# 27. Mở rộng TikTok channel monitoring

## 27.1. Mục tiêu

Theo dõi kênh bằng API chính thức, read-only.

## 27.2. Mini-spike riêng

Cần xác minh:

- Sản phẩm API phù hợp.
- OAuth flow.
- Scopes.
- Rate limit.
- Refresh token.
- Metrics có sẵn.
- Data retention.

## 27.3. Module dự kiến

```text
backend/app/integrations/tiktok/
├── oauth.py
├── client.py
├── parser.py
├── service.py
└── schemas.py
```

## 27.4. Database dự kiến

```text
integration_credentials
tiktok_channels
tiktok_videos
tiktok_metric_snapshots
oauth_states
```

## 27.5. Không làm

- Không tự Follow/Like.
- Không TDS job/claim.
- Không dùng UI automation.
- Không dùng proxy rotation.
- Không thu thập ngoài scope được cấp.

---

# 28. Định hướng tự động hóa tương lai

## 28.1. Có thể tự động hóa thêm phần nào?

Sau khi bán tự động ổn định, có thể mở rộng các phần an toàn và phù hợp:

- Tự refresh account profile.
- Tự đồng bộ session stats.
- Tự reconnect WebSocket.
- Tự retry lỗi mạng trong giới hạn.
- Tự resume pending database operation cần review.
- Tự cảnh báo rate limit.
- Tự dừng khi đạt session limit.
- Tự tạo báo cáo.
- Tự backup database.
- Tự poll analytics qua API chính thức khi được phép.
- Tự kiểm tra health của backend/database.

## 28.2. Không mở rộng thành full interaction bot

Việc biến hệ thống thành bot tự Like/Follow/Reaction/Comment sẽ thay đổi bản chất dự án:

```text
Job assistant
→ engagement automation system
```

Điều đó không chỉ là “thêm một module”.

Nó đòi hỏi:

- Điều khiển UI.
- Xử lý phiên đăng nhập.
- Xử lý thay đổi giao diện.
- Xử lý checkpoint.
- Xử lý hành vi bị giới hạn.
- Xử lý rủi ro điều khoản nền tảng.

Dự án này không thiết kế hoặc cung cấp hướng triển khai các phần đó.

## 28.3. Quyết định kiến trúc

Core hiện tại nên giữ extensible theo interface, nhưng roadmap production phải ghi:

```text
Allowed automation:
- workflow
- persistence
- monitoring
- official API analytics
- reporting
- safe retries

Not allowed:
- automated social interaction
- artificial engagement
- bypass
- anti-detection
```

---

# 29. Quyết định về proxy và xoay IP

## 29.1. Proxy có giải quyết bài toán không?

Không.

Proxy chỉ thay đổi tuyến mạng hoặc IP nhìn thấy ở một phần lưu lượng.

Proxy không chứng minh rằng hành vi là hợp lệ và không thay đổi:

- State của account.
- Lịch sử hành động.
- Nhịp tương tác.
- Session/cookie.
- Thiết bị và browser signals.
- Pattern job/claim.
- Cảnh báo tài khoản.
- Điều kiện sử dụng nền tảng.

## 29.2. Xoay IP có thể làm hệ thống kém ổn định hơn

Các rủi ro:

- Login location thay đổi.
- Phiên bị yêu cầu review.
- Kết nối chậm hoặc timeout.
- IP có reputation xấu.
- Khó debug.
- API rate-limit không nhất thiết dựa riêng trên IP.
- Tăng chi phí vận hành.
- Làm sai dữ liệu observability.
- Tạo thêm bề mặt rò rỉ credential qua proxy operator.

## 29.3. Quyết định dự án

Không đưa proxy rotation vào:

- MVP.
- Reliability roadmap.
- Multi-user roadmap.
- TikTok analytics roadmap.

Không dùng proxy để:

- Tránh rate limit.
- Tiếp tục sau checkpoint.
- Che automation.
- Xoay account.
- Né enforcement.

## 29.4. Trường hợp proxy hợp lệ ngoài phạm vi này

Một tổ chức có thể dùng corporate proxy cho:

- Egress control.
- Audit.
- Network policy.
- Security gateway.

Trong trường hợp đó proxy phải ổn định, được quản trị và không dùng để né giới hạn. Đây không phải proxy rotation.

---

# 30. Checklist bàn giao

## 30.1. Tài liệu

- [ ] Design v2.0 nằm trong `docs/`.
- [ ] Implementation plan nằm trong `docs/`.
- [ ] README trỏ đúng hai tài liệu.
- [ ] Không còn hướng dẫn SQLite/CLI là kiến trúc chính.
- [ ] Không còn ADB trong MVP.
- [ ] TikTok được tách bounded context.

## 30.2. Phase 0

- [ ] API_NOTES.
- [ ] Fixtures.
- [ ] Parser prototype.
- [ ] Parser tests.
- [ ] GO_NO_GO.

## 30.3. Backend

- [ ] FastAPI bootstrap.
- [ ] Settings.
- [ ] TokenStore.
- [ ] Redaction.
- [ ] SQLAlchemy async.
- [ ] Alembic.
- [ ] Models.
- [ ] State machine.
- [ ] TDS client.
- [ ] Services.
- [ ] Routes.
- [ ] WebSocket.
- [ ] Tests.

## 30.4. Frontend

- [ ] Vue/Vite.
- [ ] TypeScript.
- [ ] Pinia.
- [ ] Router.
- [ ] Axios.
- [ ] WebSocket.
- [ ] Dashboard.
- [ ] SessionView.
- [ ] Components.
- [ ] Tests.

## 30.5. Safety

- [ ] Token server-only.
- [ ] Manual confirmation.
- [ ] Min-wait backend.
- [ ] Session limits.
- [ ] Warning stop.
- [ ] 429 handling.
- [ ] No auto-click.
- [ ] No CAPTCHA bypass.
- [ ] No account rotation.
- [ ] No proxy rotation.
- [ ] No anti-detection.

---

# 31. Phụ lục

## 31.1. Critical files

Backend:

```text
backend/api_spike/API_NOTES.md
backend/api_spike/parser_prototype.py
backend/api_spike/GO_NO_GO.md
backend/app/config/settings.py
backend/app/core/logging.py
backend/app/core/redaction.py
backend/app/core/security/token_store.py
backend/app/db/models.py
backend/app/db/migrations/0001_init.py
backend/app/jobs/state_machine.py
backend/app/jobs/service.py
backend/app/claims/service.py
backend/app/sessions/service.py
backend/app/providers/tds/client.py
backend/app/providers/tds/parser.py
backend/app/providers/tds/errors.py
backend/app/platforms/facebook/urls.py
backend/app/api/routes/*
backend/app/ws/manager.py
backend/app/main.py
```

Frontend:

```text
frontend/src/api/*
frontend/src/stores/*
frontend/src/types/*
frontend/src/views/Dashboard.vue
frontend/src/views/SessionView.vue
frontend/src/components/*
```

Root:

```text
docker-compose.yml
README.md
docs/Facebook_TDS_Job_Assistant_Design_v2.0_Web.md
docs/IMPLEMENTATION_PLAN.md
```

## 31.2. Definition of Done

Một module chỉ hoàn thành khi:

- Có type hints.
- Có public contract rõ.
- Có validation.
- Có unit test.
- Không log secret.
- Có timeout cho I/O.
- Có error mapping.
- Không nuốt exception.
- Có integration test khi chạm DB/network.
- Có tài liệu cấu hình.
- Không vi phạm state machine invariant.

## 31.3. Quyết định kiến trúc tóm tắt

| Chủ đề | Quyết định |
|---|---|
| UI | Vue 3 web-only |
| Backend | FastAPI async |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy 2.0 async |
| Migration | Alembic |
| HTTP client | httpx async |
| Realtime | WebSocket |
| Fetch | Manual trong MVP |
| Link opening | Frontend `window.open` |
| Claim | Backend-only |
| Confirmation | Bắt buộc thủ công |
| Token | Server-only qua TokenStore |
| Local MVP | Một bootstrap account |
| Multi-user | Thiết kế sẵn, chưa build auth |
| TikTok | Bounded context analytics riêng |
| Auto interaction | Không triển khai |
| Proxy rotation | Không triển khai |

---

# Kết luận

Phiên bản 2.0 chuyển tài liệu từ một CLI assistant dùng SQLite thành một web app có kiến trúc rõ ràng:

```text
Vue 3
→ FastAPI
→ PostgreSQL
→ TDS provider
```

Các invariant quan trọng vẫn giữ nguyên:

- API spike trước provider production.
- Backend là source of truth.
- Manual confirmation trước claim.
- Không claim trùng.
- Token không rời server.
- Tôn trọng rate limit.
- Dừng khi có cảnh báo.
- Không tự động tương tác Facebook.
- Không dùng proxy rotation hoặc anti-detection.

Thứ tự triển khai:

```text
1. API spike
2. Core backend độc lập API
3. GO/No-Go
4. TDS provider
5. REST + WebSocket
6. Vue frontend
7. E2E
8. Pilot
9. Go/No-Go mở rộng
10. Reliability hoặc TikTok analytics riêng
```
