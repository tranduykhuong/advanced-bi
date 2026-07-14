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

# Mondrian cube schema + its Saiku OLAP datasource (points at postgres_dw/dds).
[ -f "$DATA_DIR/Vietnam_Trade_Analysis_Cube.xml" ] \
  || cp /opt/saiku-seed/data/Vietnam_Trade_Analysis_Cube.xml "$DATA_DIR/"
[ -f "$DS_DIR/tradedw.sds" ] \
  || cp /opt/saiku-seed/datasources/tradedw.sds "$DS_DIR/"

# The launcher's repo staging misses this file, causing a recurring
# .repo_version write error on every authenticated request — pre-create it.
[ -f "$ETC_DIR/.repo_version" ] || echo 1 > "$ETC_DIR/.repo_version"

exec /usr/local/bin/saiku-entrypoint "$@"
