# Trade Map Ingest (VPS1)

Tài liệu này hướng dẫn các thành viên chạy ingest dữ liệu Trade Map vào database nguồn `trademap_db` trên VPS1.

## 1) Mục tiêu ingest

- Load master data:
  - `country` từ `Trade_Map_-_Data_Availability.csv`
  - `product` từ `Trade_Map_-_List_of_exported_products_for_the_selected_product_(All_products).csv`
- Load dữ liệu giao dịch vào `trade_record` từ các file Trade Map.
- Với file bilateral (`Trade_Map_-_Bilateral_trade_between_*_and_Viet_Nam.csv`):
  - chỉ lấy block **exports to Viet Nam**
  - theo **tháng** (`YYYY-MMM`)
  - theo **từng product_code** (bao gồm `TOTAL`).

## 2) Chuẩn bị môi trường

Từ root project:

```bash
cd vps1_data_sources/trademap_ingest
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Script đọc biến môi trường DB từ file `.env` ở root project (qua `config.py`).

Biến quan trọng:

- `VPS1_POSTGRES_DB` (mặc định `trademap_db`)
- `VPS1_POSTGRES_USER` (mặc định `trademap_admin`)
- `VPS1_POSTGRES_PASSWORD` (bắt buộc)
- `VPS1_DB_HOST` / `VPS1_DB_PORT` (nếu cần override host/port)

## 3) Tạo schema (chạy 1 lần)

Nếu DB chưa có bảng:

```bash
psql "postgresql://trademap_admin:<password>@localhost:5434/trademap_db" -f schema.sql
```

## 4) Cách chạy ingest

### A. Chạy đầy đủ master + trade files chỉ định

```bash
python ingest_trademap.py \
  --data-dir ../raw_data \
  ../raw_data/Trade_Map_-_Bilateral_trade_between_Zambia_and_Viet_Nam.csv

# Chỉ nạp master
python ingest_trademap.py --data-dir ../raw_data
# (không có trade_files → chỉ chạy master nếu không có --skip-master)
```

### B. Chỉ chạy trade files (bỏ qua master)

Dùng khi `country` và `product` đã có sẵn:

```bash
python ingest_trademap.py \
  --skip-master \
  --data-dir ../raw_data \
  ../raw_data/Trade_Map_-_Bilateral_trade_between_Türkiye_and_Viet_Nam.csv
```

### C. Chạy toàn bộ file trade trong 1 folder

Script hỗ trợ `--trade-dir` để tự quét file trong thư mục.

Ví dụ folder `vps1_data_sources/raw_data/trademap_exports/`:

```bash
python ingest_trademap.py \
  --skip-master \
  --data-dir ../raw_data \
  --trade-dir trademap_exports
```

Ghi chú:

- Nếu truyền `trade_files` positional, script sẽ ưu tiên danh sách đó.
- Nếu không truyền `trade_files`, script sẽ lấy tất cả file trong `--trade-dir`.

## 5) Verify nhanh sau khi chạy

```sql
SELECT COUNT(*) FROM trade_record;

SELECT c_exp.name AS exporter, c_imp.name AS importer, COUNT(*) AS rows
FROM trade_record tr
JOIN country c_exp ON c_exp.id = tr.exporter_id
JOIN country c_imp ON c_imp.id = tr.importer_id
GROUP BY 1,2
ORDER BY rows DESC
LIMIT 20;
```

## 6) Lỗi thường gặp

- `No trade rows were written ... check country/product master data`
  - Thiếu dữ liệu master `country` hoặc `product`.
  - Chạy lại không có `--skip-master` để nạp master trước.
- `VPS1_DB_PASSWORD ... is required`
  - Chưa set password DB trong `.env` hoặc env hiện tại.
- Sai đường dẫn `--data-dir` / `--trade-dir`
  - Kiểm tra đường dẫn tương đối đang chạy từ `vps1_data_sources/trademap_ingest`.

