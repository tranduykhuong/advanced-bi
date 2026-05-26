FROM python:3.12-slim

RUN addgroup --system etlgroup && adduser --system --ingroup etlgroup etluser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R etluser:etlgroup /app

USER etluser

# Default: run the full pipeline.
# For interactive dev override with: docker compose run --rm etl_engine sleep infinity
CMD ["python", "run_pipeline.py"]
