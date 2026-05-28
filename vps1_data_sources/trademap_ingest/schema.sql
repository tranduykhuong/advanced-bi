-- ITC Trade Map — relational schema (VPS1 source database)

-- 1. Bảng Quốc gia
CREATE TABLE country (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL
);

-- 2. Bảng Sản phẩm
CREATE TABLE product (
    code VARCHAR(50) PRIMARY KEY,
    label TEXT NOT NULL
);

-- 3. Bảng Lưu trữ Giao dịch
-- Bilateral ingest: exporter = quốc gia xuất khẩu (Zambia, Türkiye, ...),
-- importer = Viet Nam (cố định), product_code = TOTAL hoặc mã HS từng sản phẩm.
CREATE TABLE trade_record (
    id SERIAL PRIMARY KEY,
    exporter_id INT NOT NULL,
    importer_id INT NOT NULL,
    product_code VARCHAR(50) NOT NULL,
    year INT NOT NULL,
    month INT NOT NULL,
    value_usd_k NUMERIC,

    CONSTRAINT fk_trade_exporter FOREIGN KEY (exporter_id) REFERENCES country(id) ON DELETE CASCADE,
    CONSTRAINT fk_trade_importer FOREIGN KEY (importer_id) REFERENCES country(id) ON DELETE CASCADE,
    CONSTRAINT fk_trade_product FOREIGN KEY (product_code) REFERENCES product(code) ON DELETE CASCADE,

    CONSTRAINT uq_trade_record UNIQUE (exporter_id, importer_id, product_code, year, month)
);

CREATE INDEX idx_trade_record_year_month ON trade_record(year, month);
CREATE INDEX idx_trade_record_exporter ON trade_record(exporter_id);
