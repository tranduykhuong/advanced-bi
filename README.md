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
│  └──────────────┘        │  03_load_to_dds  │─────►│  dds  (Kimball) │  │
│                          └──────────────────┘      │  cube (views)   │  │
│                                                    └─────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Warehouse Layers

| Schema | Layer | Design | Role |
|--------|-------|--------|------|
| `stg`  | Staging        | VARCHAR-heavy    | Fast truncate-and-load landing zone from all sources |
| `ods`  | Operational DS | Typed + keyed    | Integrated operational snapshot (Inmon approach) |
| `nds`  | Normalized DS  | 3NF + FKs        | Master data: countries, HS codes, reporters/partners |
| `dds`  | Dimensional DS | Star schema      | Kimball dims (SCD1/SCD2) + fact tables for OLAP |
| `cube` | Cube/Views     | SQL Views        | Pre-aggregated analytical hypercubes over DDS |

### Production VPS Mapping

| Service | VPS IP | Directory |
|---------|--------|-----------|
| Mock API / Raw Files | `134.209.99.243` | `vps1_data_sources/` |
| ETL Engine           | `178.128.23.125` | `vps2_data_integration/` |
| PostgreSQL DW        | `152.42.163.132` | `vps3_data_warehouse/` |

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
docker compose run --rm etl_engine python 01_extract/extract_trademap_api.py
docker compose run --rm etl_engine python 01_extract/extract_raw_files.py
docker compose run --rm etl_engine python 02_cleansing_and_transform/staging_to_ods.py
docker compose run --rm etl_engine python 02_cleansing_and_transform/staging_to_nds.py
docker compose run --rm etl_engine python 03_load_to_dds/nds_to_dds_scd.py
```

### 5. Interactive ETL development

Override the ETL container command to keep it alive for shell access:

```bash
docker compose run --rm etl_engine sleep infinity
# In another terminal:
docker exec -it etl_engine bash
```

### 6. Query the cube views

```bash
docker exec -it postgres_dw psql -U bi_admin -d bi_dw -c \
  "SELECT * FROM cube.v_trade_by_country_year LIMIT 10;"
```

---

## Directory Structure

```
Project/
├── docker-compose.yml          # Local dev orchestration
├── .env.example                # Environment variable template
├── .gitignore
├── README.md
├── .github/workflows/
│   └── deploy.yml              # GitHub Actions CI/CD (3 VPS targets)
├── vps1_data_sources/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py             # FastAPI app (TradeMap-style endpoints)
│   │   └── models.py           # Pydantic response schemas
│   └── raw_data/
│       ├── un_comtrade_sample.csv
│       └── gso_trade_sample.csv
├── vps2_data_integration/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── config.py               # Env-driven connection settings
│   ├── run_pipeline.py         # Full pipeline orchestrator
│   ├── common/
│   │   ├── db.py               # DB connection helper (SQLAlchemy)
│   │   └── logging_config.py   # Structured JSON logging
│   ├── 01_extract/
│   │   ├── extract_trademap_api.py
│   │   └── extract_raw_files.py
│   ├── 02_cleansing_and_transform/
│   │   ├── staging_to_ods.py
│   │   ├── staging_to_nds.py   # Includes fuzzy matching
│   │   └── late_arriving_handler.py
│   └── 03_load_to_dds/
│       └── nds_to_dds_scd.py   # SCD Type 1 & 2 upserts
└── vps3_data_warehouse/
    ├── Dockerfile
    ├── 00_init.sql             # Creates all 5 schemas + extensions
    ├── 01_staging/01_ddl_stg_trade.sql
    ├── 02_ods/01_ddl_ods_trade.sql
    ├── 03_nds/01_ddl_nds_trade.sql
    ├── 04_dds/01_ddl_dds_star.sql
    └── 05_cube/01_views_cube_trade.sql
```

---

## CI/CD: GitHub Actions Deploy

Three parallel deployment jobs are defined in `.github/workflows/deploy.yml`, each triggered on push to `main` with path filters.

### Required GitHub Secrets

Configure these in your repository under **Settings → Secrets and variables → Actions**:

| Secret | Description |
|--------|-------------|
| `SSH_PRIVATE_KEY` | Private key for SSH access to all VPS machines |
| `SSH_USER` | SSH username (e.g. `deploy` or `root`) |
| `VPS1_HOST` | `134.209.99.243` |
| `VPS2_HOST` | `178.128.23.125` |
| `VPS3_HOST` | `152.42.163.132` |
| `POSTGRES_PASSWORD` | Strong password for the warehouse DB |

### Deploy triggers

- Push to `main` with changes under `vps1_data_sources/**` → deploys to VPS1
- Push to `main` with changes under `vps2_data_integration/**` → deploys to VPS2
- Push to `main` with changes under `vps3_data_warehouse/**` → deploys to VPS3
- Manual trigger via `workflow_dispatch` deploys all three

---

## Local vs Production Hostnames

| Variable | Local (Docker Compose) | Production |
|----------|----------------------|------------|
| `DB_HOST` | `postgres_dw` (service name) | `152.42.163.132` |
| `VPS1_API_URL` | `http://mock_api:8000` | `http://134.209.99.243:8000` |

---

## ETL Pipeline Phases

```
01_extract          → loads raw data into stg.*  (TRUNCATE + load)
02_cleanse          → stg.* → ods.* → nds.*      (type cast, dedup, 3NF, fuzzy match)
03_load_to_dds      → nds.* → dds.*              (SCD1/SCD2 upserts, star keys)
cube views          → defined at init             (SQL views, no ETL step needed)
```

Late-arriving data (rows with `report_year` behind the current watermark) is handled by `02_cleansing_and_transform/late_arriving_handler.py` which reprocesses the affected partition.

---

## Development Roadmap (Out of Scope for Initial Scaffold)

- [ ] Flyway / Alembic migration runner for post-init schema evolution
- [ ] Airflow / Prefect DAG wrapping `run_pipeline.py`
- [ ] Full production hardening: TLS termination, secrets manager (Vault/AWS SSM), automated DB backups
- [ ] GitLab CI mirror of `.github/workflows/deploy.yml`
- [ ] Real TradeMap and UN Comtrade API credentials + rate-limit handling
