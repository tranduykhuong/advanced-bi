# VPS3 SQL migrations

Schema changes for **existing** databases. Run on every VPS3 deploy (see `deploy-vps3.yml`).

- **Init DDL** (`01_stage/`, `02_ods/`, …): mounted to `docker-entrypoint-initdb.d` — runs only on first empty volume.
- **Migrations** (this folder): `NNN_description.sql`, applied in sorted order; keep scripts idempotent where possible.

Add new files with incrementing numeric prefixes, e.g. `002_...sql`.
