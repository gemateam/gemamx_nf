FROM python:3.12.7-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/*

RUN pip install mlflow==2.19.0 psycopg2-binary==2.9.10 sqlalchemy==2.0.36

# GEMA MX: evita el 500 de Postgres cuando la UI envía experiment_id="..."
COPY containers/mlflow/patch_handlers.py /tmp/patch_handlers.py
RUN python /tmp/patch_handlers.py

COPY containers/mlflow/entrypoint.sh /usr/local/bin/mlflow-entrypoint
RUN chmod +x /usr/local/bin/mlflow-entrypoint

EXPOSE 5000
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/mlflow-entrypoint"]
