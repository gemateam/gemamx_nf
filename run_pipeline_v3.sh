#!/usr/bin/env bash
# =============================================================================
# run_pipeline_v3.sh — Ejecutor del Pipeline V3 (TCGA-BRCA Hispano/Latino)
#
# Consume el contrato de datos versionado exportado desde etl_tcga:
#   - Exclusivamente casos de cáncer de mama (TCGA-BRCA)
#   - Exclusivamente etnicidad autorreportada Hispana o Latina
#
# Uso:
#   bash run_pipeline_v3.sh [opciones adicionales de nextflow]
#
# Ejemplo:
#   bash run_pipeline_v3.sh -profile docker,gemamx-net,v3-tcga-hispanic
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"
RUN_NAME="tcga_brca_hispanic_$(date +%Y%m%d_%H%M%S)"
LIVE_DIR="${SCRIPT_DIR}/results/runs/_live"
TRACE_FILE="${LIVE_DIR}/${RUN_NAME}.trace.tsv"
STATUS_FILE="${LIVE_DIR}/status.json"
RUN_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
MLFLOW_URI="http://gemamx_mlflow:5000"
MLFLOW_EXPERIMENT="GEMAMX-V3-TCGA-HISPANIC"
MLFLOW_IMAGE="gemamx-cpu:1.0.0"
MLFLOW_RUN_ID=""
MLFLOW_EXPERIMENT_ID=""
GIT_COMMIT="$(git -C "${SCRIPT_DIR}" rev-parse HEAD 2>/dev/null || printf 'unknown')"

mkdir -p "${LIVE_DIR}"
: > "${TRACE_FILE}"

write_status() {
    local state="$1"
    local exit_code="${2:-null}"
    local mlflow_run_id="${3:-}"
    local updated_at
    updated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '{"run_name":"%s","status":"%s","started_at":"%s","updated_at":"%s","exit_code":%s,"trace_file":"%s","mlflow_run_id":"%s","mlflow_experiment":"%s","mlflow_experiment_id":"%s"}\n' \
        "${RUN_NAME}" "${state}" "${RUN_STARTED_AT}" "${updated_at}" \
        "${exit_code}" "$(basename "${TRACE_FILE}")" "${mlflow_run_id}" \
        "${MLFLOW_EXPERIMENT}" "${MLFLOW_EXPERIMENT_ID}" > "${STATUS_FILE}.tmp"
    mv -f "${STATUS_FILE}.tmp" "${STATUS_FILE}"
}

manage_mlflow_run() {
    docker run --rm --network gemamx_net \
        -v "${SCRIPT_DIR}:/workspace:ro" \
        -w /workspace \
        "${MLFLOW_IMAGE}" \
        python3 /workspace/bin/manage_mlflow_run.py "$@"
}

echo "=== Lanzando Pipeline V3 (TCGA-BRCA Hispano/Latino) ==="
echo "Run Name: ${RUN_NAME}"
write_status "running"
if MLFLOW_RESULT="$(manage_mlflow_run start \
    --tracking-uri "${MLFLOW_URI}" \
    --experiment "${MLFLOW_EXPERIMENT}" \
    --run-name "${RUN_NAME}" \
    --git-commit "${GIT_COMMIT}" \
    --manifest "tests/reference/tcga_hispanic_v3/manifest.json")"; then
    IFS=$'\t' read -r MLFLOW_EXPERIMENT_ID MLFLOW_RUN_ID <<< "${MLFLOW_RESULT}"
    echo "MLflow Run ID: ${MLFLOW_RUN_ID}"
else
    MLFLOW_RUN_ID=""
    MLFLOW_EXPERIMENT_ID=""
    echo "WARN: no se pudo abrir un run en MLflow; Nextflow continuará con seguimiento local" >&2
fi
write_status "running" null "${MLFLOW_RUN_ID}"

if nextflow run "${SCRIPT_DIR}/main_v3.nf" \
    -profile docker,gemamx-net,v3-tcga-hispanic \
    --run-name "${RUN_NAME}" \
    -with-trace "${TRACE_FILE}" \
    "$@"
then
    write_status "completed" 0 "${MLFLOW_RUN_ID}"
    if [[ -n "${MLFLOW_RUN_ID}" ]]; then
        manage_mlflow_run finish --tracking-uri "${MLFLOW_URI}" \
            --experiment "${MLFLOW_EXPERIMENT}" --run-name "${RUN_NAME}" \
            --status completed --exit-code 0 || \
            echo "WARN: no se pudo cerrar el run de MLflow como FINISHED" >&2
    fi
else
    exit_code=$?
    write_status "failed" "${exit_code}" "${MLFLOW_RUN_ID}"
    if [[ -n "${MLFLOW_RUN_ID}" ]]; then
        manage_mlflow_run finish --tracking-uri "${MLFLOW_URI}" \
            --experiment "${MLFLOW_EXPERIMENT}" --run-name "${RUN_NAME}" \
            --status failed --exit-code "${exit_code}" || \
            echo "WARN: no se pudo cerrar el run de MLflow como FAILED" >&2
    fi
    exit "${exit_code}"
fi

