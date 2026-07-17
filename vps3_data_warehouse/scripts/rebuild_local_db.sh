#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# rebuild_local_db.sh — re-apply the full VPS3 schema to a running local
# postgres_dw container without touching existing data rows.
#
# Why this exists: docker-entrypoint-initdb.d only runs its SQL files on a
# completely empty Postgres data volume. If the local Docker Desktop/WSL2
# volume ever loses its schema (e.g. an unclean VM shutdown flushes stale
# disk state — public.etl_batch_log / stage / ods / nds / dds all missing,
# even though the container itself starts up "healthy"), the pipeline fails
# with errors like:
#   psycopg2.errors.UndefinedTable: relation "public.etl_batch_log" does not exist
#
# This script re-runs the same canonical DDL + migrations that
# docker-entrypoint-initdb.d would have run on first boot, in the same
# order. Every statement in these files is idempotent (IF NOT EXISTS /
# ON CONFLICT / DROP ... IF EXISTS), so running this against a database
# that already has the schema is always safe — it only fixes what's
# actually missing.
#
# Usage (from repo root, requires the postgres_dw container to be running):
#   bash vps3_data_warehouse/scripts/rebuild_local_db.sh
#
# After it finishes, re-run the ETL pipeline to reload data:
#   docker compose run --rm etl_engine python run_pipeline.py --phase all
# ---------------------------------------------------------------------------
set -euo pipefail

CONTAINER="${POSTGRES_CONTAINER:-postgres_dw}"
DB_USER="${POSTGRES_USER:-bi_admin}"
DB_NAME="${POSTGRES_DB:-bi_dw}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WAREHOUSE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if ! docker ps --format '{{.Names}}' | grep -qx "${CONTAINER}"; then
    echo "ERROR: container '${CONTAINER}' is not running. Start it first, e.g.:" >&2
    echo "  docker compose up -d postgres_dw" >&2
    exit 1
fi

echo "==> Waiting for ${CONTAINER} to accept connections..."
until docker exec "${CONTAINER}" pg_isready -U "${DB_USER}" -d "${DB_NAME}" >/dev/null 2>&1; do
    sleep 1
done

apply() {
    local file="$1"
    echo "==> Applying: ${file#"${WAREHOUSE_DIR}/"}"
    docker exec -i "${CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 < "${file}"
}

# 1. Canonical DDL, in the exact order docker-entrypoint-initdb.d uses
#    (see docker-compose.yml / vps3_data_warehouse/Dockerfile).
DDL_FILES=(
    "${WAREHOUSE_DIR}/00_init.sql"
    "${WAREHOUSE_DIR}/01_stage/01_ddl_stage_trade.sql"
    "${WAREHOUSE_DIR}/01_stage/03_ddl_stage_exchange_rate.sql"
    "${WAREHOUSE_DIR}/02_ods/01_ddl_ods_trade.sql"
    "${WAREHOUSE_DIR}/02_ods/02_ddl_ods_exchange_rate.sql"
    "${WAREHOUSE_DIR}/03_nds/01_ddl_nds_trade.sql"
    "${WAREHOUSE_DIR}/03_nds/02_ddl_nds_exchange_rate.sql"
    "${WAREHOUSE_DIR}/04_dds/01_ddl_dds.sql"
)
for f in "${DDL_FILES[@]}"; do
    apply "${f}"
done

# 2. All migrations, in numeric order (same as deploy-vps3.yml on VPS3).
shopt -s nullglob
for f in "${WAREHOUSE_DIR}"/migrations/*.sql; do
    apply "${f}"
done
shopt -u nullglob

echo "==> Verifying schemas..."
docker exec "${CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" -c "\dn"

echo ""
echo "Schema rebuild complete. If any tables came back empty, reload data with:"
echo "  docker compose run --rm etl_engine python run_pipeline.py --phase all"
