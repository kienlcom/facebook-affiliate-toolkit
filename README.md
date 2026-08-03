# Facebook TDS Job Assistant

Web app bán tự động hỗ trợ làm nhiệm vụ Facebook trên TraoDoiSub (TDS). Người dùng tự thao tác Facebook và xác nhận thủ công; backend là nguồn sự thật và chỉ gọi API nhận điểm sau khi có xác nhận.

**Stack:** Vue 3 + TypeScript · FastAPI · PostgreSQL 16 · SQLAlchemy 2.0 async · Alembic.

## Tài liệu

- [Thiết kế hệ thống v2.1](docs/Facebook_TDS_Job_Assistant_Design_v2.0_Web.md) — nguồn quyết định về kiến trúc.
- [Kế hoạch triển khai](docs/IMPLEMENTATION_PLAN.md) — thứ tự thực thi + Definition of Done từng phase.

## Ranh giới an toàn

Không tự tạo Like/Follow/Comment, không tự xác nhận/claim, không proxy/account
rotation, không anti-detection và không bypass CAPTCHA/checkpoint. Local Link
Opener chỉ mở URL Facebook đã validate; nó không tạo tương tác trong tab.

## Bắt đầu

Phase hiện tại:

- Phase 0: `GO` cho profile `facebook_page`; fixtures thật đã redaction và parser
  prototype tests đã pass.
- Phase 1: hoàn thành core backend độc lập hợp đồng API TDS.
- Phase 2: hoàn thành TDS provider cho `facebook_page`, gồm parser typed,
  bounded network retry, HTTP 429 + persisted circuit breaker, redacted API
  call persistence và integration tests.
- Phase 3: hoàn thành session/job/claim services, REST API, standardized error
  envelope, account-warning protection stop, session WebSocket events và Local
  Link Opener/auto-advance tuần tự.
- Phase 4: hoàn thành Vue workflow gồm Dashboard, SessionView, typed REST/WS
  client, Pinia stores, manual/local-browser link opening, auto-open controls,
  manual confirm/skip/invalid, countdown, stats, realtime log và
  account-warning stop.
- Phase 5: chưa triển khai E2E thật với PostgreSQL/TDS và pilot.

Chạy local: xem mục "Chạy local" trong tài liệu thiết kế v2.0 (Docker Postgres → backend `uvicorn` → frontend `vite`).

Backend không khởi động nếu `backend/.env` chưa có `TDS_ACCESS_TOKEN` thật. Token chỉ được đọc server-side qua `TokenStore`, không đưa xuống frontend.

Local Link Opener mặc định tắt. Để bật trên máy local:

```dotenv
APP_ENV=development
LINK_OPENER_MODE=local_browser
AUTO_OPEN_ENABLED=true
AUTO_OPEN_INTERVAL_SECONDS=20
```

## Docker stable

Ban Docker stable khong bind-mount source, nen co the chay song song trong khi
tiep tuc phat trien local. Backend container dung Host Link Opener Companion co
token rieng de mo URL da validate tren trinh duyet Windows:

```powershell
.\scripts\stable-build.cmd
```

Truy cap `http://localhost:8080`. Auto-open van giu manual Facebook interaction,
manual confirmation va manual claim. Xem runbook tai
[docs/DOCKER_STABLE.md](docs/DOCKER_STABLE.md).
