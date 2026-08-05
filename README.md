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

## TikTok Shop Auto Scroll

Module moi them mot backend FastAPI doc lap tai `backend/main.py` va man hinh
quan ly tai frontend route `/tiktok-shop`. He thong dung iPhone X chieu man hinh
len Windows PC qua AirPlay/LonelyScreen, sau do backend goi `pyautogui` de keo
chuot tren vung cua so LonelyScreen.

### 1. Cai dat dependencies

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Frontend:

```powershell
cd frontend
npm install
```

PostgreSQL local co the dung service san co trong repo:

```powershell
docker compose up -d postgres
```

Mac dinh backend moi doc database tu:

```dotenv
DATABASE_URL=postgresql+psycopg2://tds:tds@localhost:5432/tds_assistant
```

Co the doi `DATABASE_URL` trong terminal truoc khi chay backend neu ban dung
PostgreSQL khac.

### 2. Chay backend

Chay lenh nay tu thu muc `backend`:

```powershell
uvicorn main:app --reload
```

Backend mo tai `http://localhost:8000` va tu tao bang `channels` neu chua co.

### 3. Chay frontend

Chay lenh nay tu thu muc `frontend`:

```powershell
npm run dev
```

Mo Vite URL, thuong la `http://localhost:5173`, roi vao menu `TikTok Shop`.
Frontend goi API voi base URL `http://localhost:8000`.

### 4. Setup LonelyScreen + AirPlay

1. Cai va mo LonelyScreen tren Windows PC.
2. Dam bao iPhone X va PC cung mang Wi-Fi.
3. Tren iPhone, mo Control Center -> Screen Mirroring -> chon LonelyScreen.
4. Mo TikTok/TikTok Shop tren iPhone va dat cua so LonelyScreen o vi tri co dinh.
5. Neu Windows hoi quyen firewall cho LonelyScreen, cho phep tren private network.

### 5. Can chinh toa do scroll

Trong man hinh `TikTok Shop`, bang dieu khien co cac truong:

- `Interval`: thoi gian giua moi lan vuot, tu 10s den 60s, mac dinh 30s.
- `X`: toa do ngang nam ben trong man hinh iPhone dang mirror.
- `Y start`: diem bat dau keo, thuong gan phan duoi man hinh iPhone.
- `Y end`: diem ket thuc keo, thuong gan phan tren man hinh iPhone.

Cach can nhanh:

1. De cua so LonelyScreen dung yen.
2. Chon mot diem giua man hinh iPhone lam `X`.
3. Dat `Y start` o khoang 70-85% chieu cao vung iPhone.
4. Dat `Y end` o khoang 20-35% chieu cao vung iPhone.
5. Bam `SKIP` de thu mot lan vuot ngay. Neu chuot keo sai vung, chinh lai `X`,
   `Y start`, `Y end`.
6. Khi da dung, bam `START`; backend se tu dong vuot moi `Interval` giay.

Nut `MUA` dung thread scroll va giu trang hien tai de ban thao tac mua hang thu
cong tren iPhone. Bam `START` lai khi muon tiep tuc.
