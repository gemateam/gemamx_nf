#!/usr/bin/env bash
# =============================================================================
# run_pipeline_v2.sh — wrapper para el pipeline V2 (Romero-Córdoba 2021 HM)
#
# Ejecuta main_v2.nf. La publicación (archivo en runs/<runName>/, promoción
# atómica de data/ y reinicio de la webapp) la hace el pipeline desde
# workflow.onComplete: ver docs/ALMACENAMIENTO.md §4.
# Tras la corrida, el wrapper reintenta en primer plano la subida de los
# reportes HTML al run padre en MLflow.
#
# Uso:
#   bash run_pipeline_v2.sh
#   bash run_pipeline_v2.sh -resume
#
# Variables de entorno opcionales:
#   MLFLOW_URI      URI del servidor MLflow  (default: http://localhost:5000)
#   NF_OUTDIR       Directorio de salida     (default: results)
#   NF_EXPERIMENT   Experimento en MLflow    (default: GEMAMX-V2-ROMERO)
# =============================================================================
set -euo pipefail

MLFLOW_URI="${MLFLOW_URI:-http://localhost:5000}"
NF_OUTDIR="${NF_OUTDIR:-results}"
NF_EXPERIMENT="${NF_EXPERIMENT:-GEMAMX-V2-ROMERO}"

# Detectar el outdir efectivo desde los args del usuario (--outdir <valor>).
EFFECTIVE_OUTDIR="${NF_OUTDIR}"
PREV_ARG=""
for arg in "$@"; do
    if [[ "${PREV_ARG}" == "--outdir" ]]; then
        EFFECTIVE_OUTDIR="${arg}"
    fi
    PREV_ARG="${arg}"
done
PIPELINE_INFO="${EFFECTIVE_OUTDIR}/pipeline_info"

# Generar un runName único si no se pasa -name explícito en argumentos
CUSTOM_NAME=""
PREV_ARG=""
for arg in "$@"; do
    if [[ "${PREV_ARG}" == "-name" ]]; then
        CUSTOM_NAME="${arg}"
    fi
    PREV_ARG="${arg}"
done

NAME_ARGS=()
if [ -z "${CUSTOM_NAME}" ]; then
    RUN_NAME="romero_v2_$(date +%Y%m%d_%H%M%S)"
    NAME_ARGS=(-name "${RUN_NAME}")
else
    RUN_NAME="${CUSTOM_NAME}"
fi

echo "▶ Pipeline V2 — Romero-Córdoba 2021 HM"
echo "▶ Run name  : ${RUN_NAME}"
echo "▶ Outdir    : ${NF_OUTDIR}"
echo "▶ MLflow    : ${MLFLOW_URI} / ${NF_EXPERIMENT}"

# ---------------------------------------------------------------------------
# 1. Ejecutar pipeline V2
# ---------------------------------------------------------------------------
echo "▶ Iniciando pipeline V2..."
if ! nextflow run main_v2.nf \
    -profile docker,'romero-v2' \
    "${NAME_ARGS[@]}" \
    -with-report   "${PIPELINE_INFO}/report.html" \
    -with-timeline "${PIPELINE_INFO}/timeline.html" \
    -with-dag      "${PIPELINE_INFO}/dag.html" \
    "$@"; then
    echo "✗ Pipeline V2 terminó con error."
    exit 1
fi
echo "✓ Pipeline V2 completado."

# ---------------------------------------------------------------------------
# 2. Subir reportes HTML al run padre en MLflow
# ---------------------------------------------------------------------------
echo "▶ Subiendo reportes HTML a MLflow..."
if python3 -c "import mlflow" 2>/dev/null; then
    python3 bin/upload_nf_reports.py \
        --tracking-uri  "${MLFLOW_URI}" \
        --experiment    "${NF_EXPERIMENT}" \
        --run-name      "${RUN_NAME}" \
        --pipeline-info "${PIPELINE_INFO}"
    echo "✓ Reportes subidos. Ver en: ${MLFLOW_URI}"
else
    echo "  (mlflow no disponible en host — usando gemamx-cpu:1.0.0 vía Docker)"
    ABS_PIPELINE_INFO="$(realpath "${PIPELINE_INFO}")"
    # Red del stack de este repo (docker-compose up).
    DOCKER_NET="gemamx_net"
    DOCKER_URI="http://gemamx_mlflow:5000"
    docker run --rm \
        --network "${DOCKER_NET}" \
        -v "${ABS_PIPELINE_INFO}:/nf_reports:ro" \
        -v "$(realpath bin):/workspace/bin:ro" \
        gemamx-cpu:1.0.0 \
        python3 /workspace/bin/upload_nf_reports.py \
            --tracking-uri  "${DOCKER_URI}" \
            --experiment    "${NF_EXPERIMENT}" \
            --run-name      "${RUN_NAME}" \
            --pipeline-info /nf_reports
    echo "✓ Listo. Ver en: ${MLFLOW_URI}"
fi

# ---------------------------------------------------------------------------
# 3. Asegurar que la webapp está levantada
# ---------------------------------------------------------------------------
# El pipeline ya reinicia el contenedor al promover data/ (webapp_restart).
# Aquí solo se comprueba que exista; si no, se levanta.
echo "▶ Comprobando webapp..."
if command -v docker &>/dev/null && [ -f docker-compose.yml ]; then
    if [ -n "$(docker compose ps -q webapp 2>/dev/null)" ]; then
        echo "✓ Webapp ya en ejecución. http://localhost:8080"
    else
        docker compose up -d webapp 2>&1
        echo "✓ Webapp disponible en: http://localhost:8080"
    fi
fi
