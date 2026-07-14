# BI Trade Analytics Data Warehouse

A Master's BI project implementing a **Hybrid Inmon–Kimball** data warehouse for trade analytics (UN Comtrade / GSO / TradeMap data sources).

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        DATA FLOW (Hybrid Model)                         │
│                                                                         │
│  [VPS1: Sources]          [VPS2: ETL Engine]       [VPS3: PostgreSQL]   │
│  ┌──────────────┐        ┌──────────────────┐      ┌─────────────────┐  │
│  │  FastAPI     │──────► │  01_extract      │─────►│  stg  (landing) │  │
│  │  Mock API    │        │  02_cleanse &    │─────►│  ods  (Inmon)   │  │
│  │  raw_data/   │        │     transform    │─────►│  nds  (3NF)     │  │
│  │  postgres    │        │  03_load         │─────►│  dds  (Kimball) │  │
│  │  (trademap)  │        └──────────────────┘      │  cube (views)   │  │
│  └──────────────┘                                  └─────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Warehouse Layers

| Schema  | Layer          | Design        | Role                                                 |
| ------- | -------------- | ------------- | ---------------------------------------------------- |
| `stage` | Stage          | VARCHAR-heavy | Fast truncate-and-load landing zone from all sources |
| `ods`   | Operational DS | Typed + keyed | Integrated operational snapshot (Inmon approach)     |
| `nds`   | Normalized DS  | 3NF + FKs     | Master data: countries, HS codes, reporters/partners |
| `dds`   | Dimensional DS | Star schema   | Kimball dims (SCD2 on dim_country/dim_product/dim_fta) + fact tables for OLAP |
| `cube`  | Cube/Views     | SQL Views     | Pre-aggregated analytical hypercubes over DDS        |

### Production VPS Mapping

| Service              | VPS IP           | Directory                |
| -------------------- | ---------------- | ------------------------ |
| Mock API / Raw Files | `134.209.99.243` | `vps1_data_sources/`     |
| ETL Engine           | `178.128.23.125` | `vps2_data_integration/` |
| PostgreSQL DW        | `152.42.163.132` | `vps3_data_warehouse/`   |

---

## Quick Start (Local Docker Compose)

### Prerequisites

- Docker Desktop ≥ 24 with Compose v2
- `make` (optional but convenient)

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env — at minimum set POSTGRES_PASSWORD
```

### 2. Build and start all services

```bash
docker compose up --build -d
```

### 3. Verify services

```bash
# Check all containers are running
docker compose ps

# Verify DW schemas were created
docker exec postgres_dw psql -U bi_admin -d bi_dw -c "\dn"

# Hit the mock API health endpoint
curl http://localhost:8000/health

# Browse the API docs
open http://localhost:8000/docs
```

### 4. Run the ETL pipeline manually

```bash
# Run the full pipeline (extract → cleanse → load)
docker compose run --rm etl_engine python run_pipeline.py

# Or run individual phases
docker compose run --rm etl_engine python 01_extract/extract_csv_files.py
docker compose run --rm etl_engine python 02_transform/stage_to_ods.py
docker compose run --rm etl_engine python 02_transform/ods_to_nds.py
docker compose run --rm etl_engine python 03_load/nds_to_dds_scd.py
```

### 5. Interactive ETL development

Override the ETL container command to keep it alive for shell access:

```bash
docker compose run --rm etl_engine sleep infinity
# In another terminal:
docker exec -it etl_engine bash
```

### 6. Trade Map ingestion (manual — not in CI/CD)

CI/CD chỉ deploy `postgres_vps1` + `mock_api`. Đổ CSV vào `trademap_db` chạy tay trên VPS1 (hoặc local):

```bash
# 1. Đặt file CSV vào vps1_data_sources/raw_data/

# 2. Cài dependency (một lần)
cd vps1_data_sources/trademap_ingest
pip install -r requirements.txt

# 3. Trỏ env tới Postgres (local ví dụ)
export VPS1_DB_HOST=localhost
export VPS1_DB_PORT=5433
export VPS1_POSTGRES_DB=trademap_db
export VPS1_DB_USER=trademap_admin
export VPS1_DB_PASSWORD=<your_password>

# 4. Chạy ingest
python ingest_trademap.py --data-dir ../raw_data --trade-dir trademap_imports

# Kiểm tra
docker exec postgres_vps1 psql -U trademap_admin -d trademap_db -c \
  "SELECT COUNT(*) FROM trade_record;"
```

### 7. Query the cube views

```bash
docker exec -it postgres_dw psql -U bi_admin -d bi_dw -c \
  "SELECT * FROM cube.v_trade_by_country_year LIMIT 10;"
```

---

## Directory Structure

```
Project/
├── docker-compose.yml          # Local full-stack (VPS1+VPS2+VPS3)
├── docker-compose.vps1.yml     # VPS1 only: mock_api + postgres_vps1
├── .env.example                # Environment variable template
├── .gitignore
├── README.md
├── .github/workflows/
│   └── deploy-vps1.yml / deploy-vps2.yml / deploy-vps3.yml / deploy-all.yml
├── vps1_data_sources/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py             # FastAPI app (TradeMap-style endpoints)
│   │   └── models.py           # Pydantic response schemas
│   ├── trademap_ingest/        # CSV → Postgres on VPS1 (schema, config, ingest)
│   └── raw_data/
│       ├── un_comtrade_sample.csv
│       └── gso_trade_sample.csv
│       └── Trade_Map_*.csv     # ITC exports (not committed)
├── vps2_data_integration/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── config.py               # Env-driven connection settings
│   ├── run_pipeline.py         # Full pipeline orchestrator
│   ├── common/
│   │   ├── db.py               # DB connection helper (SQLAlchemy)
│   │   └── logging_config.py   # Structured JSON logging
│   ├── 01_extract/
│   │   ├── extract_text_files.py
│   │   └── extract_csv_files.py
│   ├── 02_transform/
│   │   ├── stage_to_ods.py
│   │   ├── ods_to_nds.py   # Includes fuzzy matching
│   │   └── late_arriving_handler.py
│   └── 03_load/
│       └── nds_to_dds_scd.py   # SCD Type 2 upserts (dim_country/dim_product/dim_fta)
└── vps3_data_warehouse/
    ├── Dockerfile
    ├── 00_init.sql             # Creates all 5 schemas + extensions
    ├── 01_stage/01_ddl_stg_trade.sql
    ├── 02_ods/01_ddl_ods_trade.sql
    ├── 03_nds/01_ddl_nds_trade.sql
    └── 04_dds/01_ddl_dds_star.sql
```

---

## CI/CD: GitHub Actions Deploy

Four workflows under `.github/workflows/` — each VPS has its own file with native `paths:` filters:

| Workflow file | Target | Push paths |
|---------------|--------|------------|
| `deploy-vps1.yml` | VPS1 Mock API + Trade Map DB | `vps1_data_sources/**`, `docker-compose.vps1.yml` |
| `deploy-vps3.yml` | VPS3 PostgreSQL | `vps3_data_warehouse/**`, `docker-compose.yml` |
| `deploy-vps2.yml` | VPS2 ETL | `vps2_data_integration/**`, `docker-compose.yml` |
| `deploy-all.yml` | Full stack (manual) | `workflow_dispatch` only — runs VPS3 → VPS1 → VPS2 |

### Required GitHub Secrets & Variables

**Secrets** (Settings → Secrets and variables → Actions → Secrets):

| Secret                   | Description                                    |
| ------------------------ | ---------------------------------------------- |
| `SSH_PRIVATE_KEY`        | Private key for SSH access to all VPS machines |
| `SSH_USER`               | SSH username (e.g. `deploy` or `root`)         |
| `POSTGRES_PASSWORD`      | Strong password for the warehouse DB (VPS3)    |
| `VPS1_POSTGRES_PASSWORD` | Password for Trade Map source DB (VPS1 + VPS2) |

**Variables** (Settings → Secrets and variables → Actions → Variables):

| Variable    | Value            |
| ----------- | ---------------- |
| `VPS1_HOST` | `134.209.99.243` |
| `VPS2_HOST` | `178.128.23.125` |
| `VPS3_HOST` | `152.42.163.132` |

### Deploy triggers

- Push to `main` changing `vps1_data_sources/**` → runs `deploy-vps1.yml`
- Push to `main` changing `vps2_data_integration/**` → runs `deploy-vps2.yml`
- Push to `main` changing `vps3_data_warehouse/**` → runs `deploy-vps3.yml`
- Push changing `docker-compose.yml` → runs all three (each workflow matches that path)
- Manual full deploy: Actions → **Deploy All VPS (Full Stack)** → Run workflow

---

## Local vs Production Hostnames

| Variable | Local (Docker Compose) | Production |
|----------|----------------------|------------|
| `DB_HOST` | `postgres_dw` (service name) | `152.42.163.132` |
| `VPS1_DB_HOST` | `postgres_vps1` (service name) | `134.209.99.243` |
| `VPS1_API_URL` | `http://mock_api:8000` | `http://134.209.99.243:8000` |

---

## ETL Pipeline Phases

```
01_extract          → loads raw data into stage.*  (TRUNCATE + load)
02_cleanse          → stage.* → ods.* → nds.*      (type cast, dedup, 3NF, fuzzy match)
03_load             → nds.* → dds.*              (SCD2 upserts, star keys)
cube views          → defined at init             (SQL views, no ETL step needed)
```

Late-arriving data (rows with `report_year` behind the current watermark) is handled by `02_transform/late_arriving_handler.py` which reprocesses the affected partition.

---

## Development Roadmap (Out of Scope for Initial Scaffold)

- [ ] Flyway / Alembic migration runner for post-init schema evolution
- [ ] Airflow / Prefect DAG wrapping `run_pipeline.py`
- [ ] Full production hardening: TLS termination, secrets manager (Vault/AWS SSM), automated DB backups
- [ ] GitLab CI mirror of `.github/workflows/deploy.yml`
- [ ] Real TradeMap and UN Comtrade API credentials + rate-limit handling
