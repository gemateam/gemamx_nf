#!/usr/bin/env bash
set -euo pipefail

: "${MLFLOW_BACKEND_STORE_URI:=sqlite:////mlflow/mlflow.db}"
: "${MLFLOW_ARTIFACT_ROOT:=/mlflow/artifacts}"

mkdir -p "$MLFLOW_ARTIFACT_ROOT"

exec mlflow server \
  --host 0.0.0.0 \
  --port 5000 \
  --backend-store-uri "$MLFLOW_BACKEND_STORE_URI" \
  --default-artifact-root "$MLFLOW_ARTIFACT_ROOT" \
  --serve-artifacts
