#!/bin/bash
set -e

echo "Restoring MLflow database from dump..."
pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists /docker-entrypoint-initdb.d/mlflow_dump.dump || true
echo "MLflow restore completed."

