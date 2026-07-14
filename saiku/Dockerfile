# =============================================================================
# Saiku (Spicule 2026 relaunch) with the PostgreSQL driver + Vietnam Trade
# Analysis cube baked in.
#
# The base image ships without a PostgreSQL JDBC driver, so a Mondrian
# datasource pointing at postgres_dw fails with "No suitable driver". The
# driver is added to the JVM boot classpath (see JAVA_OPTS in
# docker-compose.yml) so Mondrian's Class.forName can load it — `java -jar`
# ignores -cp, and the fat jar has no external lib dir, so bootclasspath is
# the reliable injection point.
#
# The cube schema + datasource are seeded into the saiku-home volume at start
# by seed-entrypoint.sh (the base image declares /app/saiku-home a VOLUME, so
# they can't be baked into that path directly).
#
# Build context is the repo root (see docker-compose.yml) so the canonical
# Vietnam_Trade_Analysis_Cube.mondrian.xml can be copied without duplication.
# =============================================================================
FROM ghcr.io/spiculedata/saiku

USER root

# PostgreSQL JDBC driver, fetched from Maven Central at build time (ADD handles
# the download natively — no curl needed in the base image).
ADD https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.3/postgresql-42.7.3.jar /drivers/postgresql.jar
RUN chmod 644 /drivers/postgresql.jar
COPY Vietnam_Trade_Analysis_Cube.mondrian.xml /opt/saiku-seed/data/Vietnam_Trade_Analysis_Cube.xml
COPY saiku/tradedw.sds /opt/saiku-seed/datasources/tradedw.sds
COPY saiku/dashboards /opt/saiku-seed/homes-admin
COPY saiku/seed-entrypoint.sh /usr/local/bin/seed-entrypoint

RUN chmod +x /usr/local/bin/seed-entrypoint

ENTRYPOINT ["/usr/local/bin/seed-entrypoint"]
CMD ["serve"]
