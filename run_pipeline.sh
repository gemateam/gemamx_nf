#!/usr/bin/env bash
# =============================================================================
# run_pipeline.sh — wrapper de ejecución de gemamx_nf
#
# Ejecuta el pipeline Nextflow y luego sube automáticamente los reportes HTML
# (report, timeline, dag) al run padre en MLflow.
#
# Uso:
#   bash run_pipeline.sh [opciones de nextflow]
#
# Ejemplos:
#   bash run_pipeline.sh -profile docker,test
#   bash run_pipeline.sh -profile docker,platform-net
#   bash run_pipeline.sh -profile docker,test -resume
#
# Variables de entorno opcionales:
#   MLFLOW_URI      URI del servidor MLflow (default: http://localhost:5000)
#   NF_OUTDIR       Directorio de salida    (default: results)
#   NF_EXPERIMENT   Experimento en MLflow   (default: GEMAMX-V1-NF)
# =============================================================================
set -euo pipefail

MLFLOW_URI="${MLFLOW_URI:-http://localhost:5000}"
NF_OUTDIR="${NF_OUTDIR:-results}"
NF_EXPERIMENT="${NF_EXPERIMENT:-GEMAMX-V1-NF}"

PIPELINE_INFO="${NF_OUTDIR}/pipeline_info"

# ---------------------------------------------------------------------------
# 1. Ejecutar pipeline Nextflow
# ---------------------------------------------------------------------------
echo "▶ Iniciando pipeline..."
nextflow run . \
    -with-report   "${PIPELINE_INFO}/report.html" \
    -with-timeline "${PIPELINE_INFO}/timeline.html" \
    -with-dag      "${PIPELINE_INFO}/dag.html" \
    "$@"

NF_EXIT=$?

if [ $NF_EXIT -ne 0 ]; then
    echo "✗ Pipeline terminó con error (código $NF_EXIT). No se suben reportes."
    exit $NF_EXIT
fi

echo "✓ Pipeline completado."

# ---------------------------------------------------------------------------
# 2. Obtener el runName de la última corrida desde el log de Nextflow
# ---------------------------------------------------------------------------
# Nextflow escribe en .nextflow.log líneas como:
#   [main] INFO nextflow.Session - Run name: friendly_swanson
RUN_NAME=$(grep -o "Run name: [a-z_]*" .nextflow.log 2>/dev/null | tail -1 | awk '{print $NF}')

if [ -z "${RUN_NAME}" ]; then
    echo "WARN: no se pudo extraer el run name del log. Sube los reportes manualmente:"
    echo "  python bin/upload_nf_reports.py \\"
    echo "    --tracking-uri ${MLFLOW_URI} \\"
    echo "    --experiment   ${NF_EXPERIMENT} \\"
    echo "    --run-name     <run_name> \\"
    echo "    --pipeline-info ${PIPELINE_INFO}"
    exit 0
fi

echo "▶ Run name detectado: ${RUN_NAME}"

# ---------------------------------------------------------------------------
# 3. Subir reportes HTML al run padre en MLflow
# ---------------------------------------------------------------------------
echo "▶ Subiendo reportes HTML a MLflow..."
python bin/upload_nf_reports.py \
    --tracking-uri  "${MLFLOW_URI}" \
    --experiment    "${NF_EXPERIMENT}" \
    --run-name      "${RUN_NAME}" \
    --pipeline-info "${PIPELINE_INFO}"

echo "✓ Listo. Consulta los reportes en: ${MLFLOW_URI}"

# ---------------------------------------------------------------------------
# 4. Levantar (o recargar) la webapp
# ---------------------------------------------------------------------------
echo "▶ Levantando webapp..."
if command -v docker &>/dev/null && [ -f docker-compose.yml ]; then
    docker compose up -d webapp 2>&1
    echo "✓ Web app disponible en: http://localhost:8080"
else
    echo "INFO: Docker no disponible — levanta la webapp manualmente:"
    echo "  docker compose up -d webapp"
fi
