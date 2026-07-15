# Dashboard MDX Queries — Vietnam Trade Analytics (Saiku)

Bộ MDX đầy đủ cho **17 tile** của dashboard, chia theo 3 tab. Mỗi tile cũng có file rời trong [docs/mdx/](mdx/).

Dùng trong Saiku: `http://localhost:8080/ui/` → login `admin`/`admin` → **New Query** → nút `</>` (MDX mode)
→ dán MDX → chọn loại chart trên toolbar → **Save** → kéo vào dashboard.

## Nguyên tắc lọc thời gian (quan trọng)

- **KHÔNG hard-code năm/tháng trong tile.** Thời gian do **Dashboard filter** (dim_time) điều khiển — thêm 1 filter dim_time ở cấp dashboard, nó áp cho mọi tile chung chiều thời gian, người xem chọn năm/quý/tháng thì cả dashboard đổi theo.
- **Không lọc theo nguồn.** DDS đã sạch/khử trùng trong ETL → cộng cả 3 nguồn là đúng. `Source System` chỉ dùng để **so sánh** (tile ⑯).
- **Ngoại lệ ⑤ GrowthRateMoM:** cần ngữ cảnh tháng (so tháng trước) → dùng `Tail([dim_time].[month].Members, 1)` lấy tháng mới nhất động, vẫn không hard-code.
- **KPI phải có 1 trục ROWS** mới hiển thị được trong Saiku (measure-only → "0 rows", không vẽ). Các KPI dùng `[dim_time].[year].Members` trên ROWS — vừa hiện số, vừa để dashboard filter thu hẹp.

**Quy ước tên:** Flow `[Flow Type].[Flow Type].[true]`=Xuất, `[false]`=Nhập. Cube mặc định `[Vietnam_Trade_Analysis_Cube]`; tile ⑬ → `[FTA_Utilization_Cube]`, tile ⑰ → `[Exchange_Rate_Cube]`.

---

## TAB 1 — Tổng quan điều hành

### ① KPI — Tổng kim ngạch  *(có sẵn: DB1_KPI_TongGiaTri)* · KPI
```mdx
SELECT {[Measures].[TradeValue_VND]} ON COLUMNS,
  NON EMPTY [dim_time].[year].Members ON ROWS
FROM [Vietnam_Trade_Analysis_Cube]
```

### ② KPI — Xuất khẩu  *(sửa: thêm lọc Flow=Export)* · KPI
```mdx
SELECT {[Measures].[TradeValue_VND]} ON COLUMNS,
  NON EMPTY [dim_time].[year].Members ON ROWS
FROM [Vietnam_Trade_Analysis_Cube]
WHERE ([Flow Type].[Flow Type].[true])
```

### ③ KPI — Nhập khẩu  *(sửa: trước lọc nhầm [true]=Xuất)* · KPI
```mdx
SELECT {[Measures].[TradeValue_VND]} ON COLUMNS,
  NON EMPTY [dim_time].[year].Members ON ROWS
FROM [Vietnam_Trade_Analysis_Cube]
WHERE ([Flow Type].[Flow Type].[false])
```

### ④ KPI — Cán cân thương mại  *(có sẵn: DB1_KPI_CanCan)* · KPI
```mdx
SELECT {[Measures].[TradeSurplus]} ON COLUMNS,
  NON EMPTY [dim_time].[year].Members ON ROWS
FROM [Vietnam_Trade_Analysis_Cube]
```

### ⑤ KPI — Tăng trưởng MoM  *(MỚI — ngoại lệ giữ ngữ cảnh tháng)* · KPI
```mdx
SELECT {[Measures].[GrowthRateMoM]} ON COLUMNS,
  NON EMPTY Tail([dim_time].[month].Members, 1) ON ROWS
FROM [Vietnam_Trade_Analysis_Cube]
```

### ⑥ Line — Xuất/Nhập theo tháng  *(sửa: tách 2 đường)* · Line
```mdx
SELECT NON EMPTY CrossJoin(
    {[Flow Type].[Flow Type].[true], [Flow Type].[Flow Type].[false]},
    {[Measures].[TradeValue_VND]}
  ) ON COLUMNS,
  NON EMPTY [dim_time].[month].Members ON ROWS
FROM [Vietnam_Trade_Analysis_Cube]
```

### ⑦ Treemap — Cơ cấu nhóm hàng  *(có sẵn: DB1_Treemap_Chapter)* · Treemap
```mdx
SELECT {[Measures].[TradeValue_VND], [Measures].[SharePercent]} ON COLUMNS,
  NON EMPTY [dim_product].[chapter_name].Members ON ROWS
FROM [Vietnam_Trade_Analysis_Cube]
```

### ⑧ Bar — Kim ngạch theo khu vực  *(có sẵn: DB1_Bar_KhuVuc)* · Bar
```mdx
SELECT {[Measures].[TradeValue_VND]} ON COLUMNS,
  NON EMPTY [dim_country].[region].Members ON ROWS
FROM [Vietnam_Trade_Analysis_Cube]
```

### ⑨ Donut — Xuất vs Nhập  *(có sẵn: DB1_Donut_ExpImp)* · Donut/Pie
```mdx
SELECT {[Measures].[TradeValue_VND]} ON COLUMNS,
  NON EMPTY [Flow Type].[Flow].Members ON ROWS
FROM [Vietnam_Trade_Analysis_Cube]
```

---

## TAB 2 — Mặt hàng & Thị trường

### ⑩ Bar — Top 10 HS Code  *(có sẵn: BD1_Bar_TopHSCode)* · Bar ngang
```mdx
SELECT {[Measures].[TradeValue_VND]} ON COLUMNS,
  NON EMPTY TopCount([dim_product].[product_name].Members, 10, [Measures].[TradeValue_VND]) ON ROWS
FROM [Vietnam_Trade_Analysis_Cube]
```

### ⑪ Bar — Top 10 thị trường  *(MỚI)* · Bar ngang
```mdx
SELECT {[Measures].[TradeValue_VND]} ON COLUMNS,
  NON EMPTY TopCount([dim_country].[country_name].Members, 10, [Measures].[TradeValue_VND]) ON ROWS
FROM [Vietnam_Trade_Analysis_Cube]
```

### ⑫ Donut — Thị phần theo nhóm hàng  *(MỚI)* · Donut/Pie
```mdx
SELECT {[Measures].[SharePercent]} ON COLUMNS,
  NON EMPTY [dim_product].[chapter_name].Members ON ROWS
FROM [Vietnam_Trade_Analysis_Cube]
```

### ⑬ Bar — Tận dụng FTA  *(MỚI — cube FTA)* · Bar
```mdx
SELECT {[Measures].[UtilizationRate]} ON COLUMNS,
  NON EMPTY [dim_fta].[fta_name].Members ON ROWS
FROM [FTA_Utilization_Cube]
```

---

## TAB 3 — Rủi ro & Chất lượng dữ liệu

### ⑭ KPI — Tỷ lệ bất cân xứng  *(MỚI)* · KPI
```mdx
SELECT {[Measures].[AsymmetryRatio]} ON COLUMNS,
  NON EMPTY [dim_time].[year].Members ON ROWS
FROM [Vietnam_Trade_Analysis_Cube]
```

### ⑮ Line — Bất cân xứng theo tháng  *(MỚI)* · Line
```mdx
SELECT {[Measures].[AsymmetryRatio]} ON COLUMNS,
  NON EMPTY [dim_time].[month].Members ON ROWS
FROM [Vietnam_Trade_Analysis_Cube]
```

### ⑯ Stacked bar — Mirror stats theo nguồn  *(MỚI — so sánh nguồn)* · Stacked bar
```mdx
SELECT {[Measures].[TradeValue_VND]} ON COLUMNS,
  NON EMPTY [Source System].[Source].Members ON ROWS
FROM [Vietnam_Trade_Analysis_Cube]
```
> Tile **duy nhất** dùng `Source System` — cố ý tách theo nguồn để so sánh (mirror statistics, VĐ #7).

### ⑰ Line — Biến động tỷ giá USD/VND  *(MỚI — cube tỷ giá)* · Line
```mdx
SELECT {[Measures].[ExchangeRate_Avg], [Measures].[ExchangeRate_Max], [Measures].[ExchangeRate_Min]} ON COLUMNS,
  NON EMPTY [dim_time].[month].Members ON ROWS
FROM [Exchange_Rate_Cube]
```

---

## Ghi chú

- **Dashboard filter dim_time** thay cho WHERE thời gian trong tile → người xem chọn năm/quý/tháng, cả dashboard đổi theo. (Ngoại lệ ⑤ dùng `Tail` lấy tháng mới nhất động.)
- **Anomaly detection** (Isolation Forest) không nằm ở đây — là ML, chạy bằng Python trên `dds.fact_trade_transaction`.
- Cube đang trỏ **production** (`152.42.163.132`) → MDX trả số liệu production thật (633,316 dòng).
- File rời từng tile: [docs/mdx/](mdx/) (01…17).
