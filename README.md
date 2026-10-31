# EduNova

Giao diện hiện tại vẫn chạy bằng Flask và Jinja, không bị thay đổi. Dự án đã có sẵn lớp React riêng để chuyển đổi dần từng trang khi cần, không cần làm lại toàn bộ một lần.

## Công nghệ

- Backend: Flask + SQLite (dữ liệu hiện hữu)
- Frontend mở rộng: React 19 + TypeScript + Vite
- Dữ liệu phía client: TanStack Query, Axios, Zustand và Zod
- Production server: Waitress

## Chạy ứng dụng hiện tại

```powershell
pip install -r requirements.txt
python app.py
```

## Chạy React để phát triển từng trang mới

```powershell
cd frontend
npm install
npm run dev
```

Vite chạy cổng `5173` và tự chuyển tiếp các request `/api` về Flask ở cổng `5000`. React hiện chưa render giao diện riêng, nhằm bảo đảm giao diện Flask đang dùng không thay đổi. Khi chuyển từng trang, thêm component vào `frontend/src` rồi thay thế đúng trang đó sau khi đã kiểm tra giao diện.

## Lưu trữ và triển khai

SQLite vẫn là lựa chọn phù hợp cho dự án cá nhân/nhóm nhỏ. Trước khi đưa lên nhiều người dùng đồng thời, nên chuyển sang PostgreSQL; schema và các API hiện tại có thể được chuyển từng bước, không ảnh hưởng giao diện.

Để chạy production trên Windows, dùng Waitress:

```powershell
waitress-serve --call app:create_app
```
