#!/usr/bin/env bash
# =============================================================================
# Seed the Vietnam Trade Analysis cube into Saiku's saiku-home on start.
#
# The base image declares /app/saiku-home as a VOLUME, so config baked into
# that path at build time is discarded. Instead we bake the seed files into
# /opt/saiku-seed and copy them into the (possibly fresh) volume here, before
# handing off to the stock launcher. All copies are idempotent — user edits
# and saved queries in an existing volume are left untouched.
# =============================================================================
set -e

HOME_DIR="${SAIKU_HOME:-/app/saiku-home}"
DS_DIR="$HOME_DIR/repository/data/unknown/datasources"
DATA_DIR="$HOME_DIR/data"
ETC_DIR="$HOME_DIR/repository/data/unknown/etc"

mkdir -p "$DS_DIR" "$DATA_DIR" "$ETC_DIR"

# Mondrian cube schema — CODE, so ALWAYS refresh it from the image. Without
# this, a cube change never reaches an existing volume on deploy (the old copy
# stays and Saiku keeps serving the stale cube).
cp /opt/saiku-seed/data/Vietnam_Trade_Analysis_Cube.xml "$DATA_DIR/"

# Always update tradedw.sds to ensure it has correct credentials
sed -e "s|\${POSTGRES_HOST}|${POSTGRES_HOST:-postgres_dw}|g" \
    -e "s|\${POSTGRES_PORT}|${POSTGRES_PORT:-5432}|g" \
    -e "s|\${POSTGRES_DB}|${POSTGRES_DB:-bi_dw}|g" \
    -e "s|\${POSTGRES_USER}|${POSTGRES_USER:-bi_admin}|g" \
    -e "s|\${POSTGRES_PASSWORD}|${POSTGRES_PASSWORD:-admin}|g" \
    /opt/saiku-seed/datasources/tradedw.sds > "$DS_DIR/tradedw.sds"

# The launcher's repo staging misses this file, causing a recurring
# .repo_version write error on every authenticated request — pre-create it.
[ -f "$ETC_DIR/.repo_version" ] || echo 1 > "$ETC_DIR/.repo_version"

# Restore the saved dashboards + charts. We copy them into the volume 
# so new dashboards are loaded, and always overwrite to ensure the repo 
# remains the source of truth for these default dashboards.
ADMIN_HOME="$HOME_DIR/repository/data/unknown/homes/admin"
mkdir -p "$ADMIN_HOME"
if [ -d "/opt/saiku-seed/homes-admin" ]; then
  cd /opt/saiku-seed/homes-admin || exit
  find . -type f | while read -r f; do
    mkdir -p "$ADMIN_HOME/$(dirname "$f")"
    cp "$f" "$ADMIN_HOME/$f"
  done
fi

exec /usr/local/bin/saiku-entrypoint "$@"
