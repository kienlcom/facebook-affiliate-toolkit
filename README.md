# Facebook TDS Job Assistant

Web app bán tự động hỗ trợ làm nhiệm vụ Facebook trên TraoDoiSub (TDS). Người dùng tự thao tác Facebook và xác nhận thủ công; backend là nguồn sự thật và chỉ gọi API nhận điểm sau khi có xác nhận.

**Stack:** Vue 3 + TypeScript · FastAPI · PostgreSQL 16 · SQLAlchemy 2.0 async · Alembic.

## Tài liệu

- [Thiết kế hệ thống v2.0](docs/Facebook_TDS_Job_Assistant_Design_v2.0_Web.md) — nguồn quyết định về kiến trúc.
- [Kế hoạch triển khai](docs/IMPLEMENTATION_PLAN.md) — thứ tự thực thi + Definition of Done từng phase.

## Ranh giới an toàn

Không auto-click/UI automation, không proxy/account rotation, không anti-detection, không bypass CAPTCHA/checkpoint. TikTok (tương lai) chỉ dùng API chính thức, read-only.

## Bắt đầu

Phase hiện tại:

- Phase 0: `GO` cho profile `facebook_page`; fixtures thật đã redaction và parser
  prototype tests đã pass.
- Phase 1: hoàn thành core backend độc lập hợp đồng API TDS.
- Phase 2: hoàn thành TDS provider cho `facebook_page`, gồm parser typed,
  bounded network retry, HTTP 429 + persisted circuit breaker, redacted API
  call persistence và integration tests.
- Phase 3: hoàn thành session/job/claim services, REST API, standardized error
  envelope, account-warning protection stop và session WebSocket events.
- Phase 4: hoàn thành Vue workflow gồm Dashboard, SessionView, typed REST/WS
  client, Pinia stores, manual open/confirm/skip/invalid, countdown, stats,
  realtime log và account-warning stop.
- Phase 5: chưa triển khai E2E thật với PostgreSQL/TDS và pilot.

Chạy local: xem mục "Chạy local" trong tài liệu thiết kế v2.0 (Docker Postgres → backend `uvicorn` → frontend `vite`).

Backend không khởi động nếu `backend/.env` chưa có `TDS_ACCESS_TOKEN` thật. Token chỉ được đọc server-side qua `TokenStore`, không đưa xuống frontend.
