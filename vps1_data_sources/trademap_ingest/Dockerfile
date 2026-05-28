# Optional — for manual runs only (not used by docker-compose or CI/CD).
#   docker build -f trademap_ingest/Dockerfile -t trademap-ingest ./vps1_data_sources
#   docker run --rm --network host -e VPS1_DB_HOST=localhost ...

FROM python:3.12-slim

WORKDIR /app/trademap_ingest

COPY trademap_ingest/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY trademap_ingest/ ./

ENTRYPOINT ["python", "ingest_trademap.py"]
