FROM postgres:16-alpine

# Copy all init SQL into the standard init directory.
# The numeric prefix on file names guarantees execution order.
COPY 00_init.sql                        /docker-entrypoint-initdb.d/00_init.sql
COPY 01_staging/01_ddl_stg_trade.sql   /docker-entrypoint-initdb.d/01_ddl_stg_trade.sql
COPY 02_ods/01_ddl_ods_trade.sql       /docker-entrypoint-initdb.d/02_ddl_ods_trade.sql
COPY 03_nds/01_ddl_nds_trade.sql       /docker-entrypoint-initdb.d/03_ddl_nds_trade.sql
COPY 04_dds/01_ddl_dds_star.sql        /docker-entrypoint-initdb.d/04_ddl_dds_star.sql
COPY 05_cube/01_views_cube_trade.sql   /docker-entrypoint-initdb.d/05_views_cube_trade.sql

EXPOSE 5432
