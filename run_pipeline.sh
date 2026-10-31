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
    echo "  # Si mlflow está instalado en el host:"
    echo "  python3 bin/upload_nf_reports.py \\"
    echo "    --tracking-uri ${MLFLOW_URI} \\"
    echo "    --experiment   ${NF_EXPERIMENT} \\"
    echo "    --run-name     <run_name> \\"
    echo "    --pipeline-info ${PIPELINE_INFO}"
    echo ""
    echo "  # Si no (usar Docker):"
    echo "  docker run --rm --network gemacont_default \\"
    echo "    -v \$(realpath ${PIPELINE_INFO}):/nf_reports:ro \\"
    echo "    -v \$(realpath bin):/workspace/bin:ro \\"
    echo "    gemamx-cpu:1.0.0 python3 /workspace/bin/upload_nf_reports.py \\"
    echo "    --tracking-uri http://mlflow:5000 \\"
    echo "    --experiment   ${NF_EXPERIMENT} \\"
    echo "    --run-name     <run_name> \\"
    echo "    --pipeline-info /nf_reports"
    exit 0
fi

echo "▶ Run name detectado: ${RUN_NAME}"

# ---------------------------------------------------------------------------
# 3. Subir reportes HTML al run padre en MLflow
# ---------------------------------------------------------------------------
# upload_nf_reports.py necesita mlflow instalado. En el host puede no estar
# disponible; se usa la imagen gemamx-cpu:1.0.0 si python3/mlflow no existen.
# La URI se adapta según si corremos en host (localhost) o en Docker (mlflow:5000).
# ---------------------------------------------------------------------------
echo "▶ Subiendo reportes HTML a MLflow..."

# Resolver imagen y URI según disponibilidad de mlflow en el host
if python3 -c "import mlflow" 2>/dev/null; then
    UPLOAD_CMD="python3"
    UPLOAD_URI="${MLFLOW_URI}"
    UPLOAD_PIPELINE_INFO="${PIPELINE_INFO}"
    UPLOAD_SCRIPT="bin/upload_nf_reports.py"
else
    echo "  (mlflow no disponible en host — usando gemamx-cpu:1.0.0 vía Docker)"
    # Detectar red: platform-net → gemacont_default, gemamx-net → gemamx_net, default → gemacont_default
    if echo "$*" | grep -q "platform-net"; then
        DOCKER_NET="gemacont_default"
        DOCKER_URI="http://mlflow:5000"
    elif echo "$*" | grep -q "gemamx-net"; then
        DOCKER_NET="gemamx_net"
        DOCKER_URI="http://gemamx_mlflow:5000"
    else
        DOCKER_NET="gemacont_default"
        DOCKER_URI="http://mlflow:5000"
    fi
    ABS_PIPELINE_INFO="$(realpath "${PIPELINE_INFO}")"
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
    echo "✓ Listo. Consulta los reportes en: ${MLFLOW_URI}"
    # El resto del script no necesita ejecutar el upload_cmd
    UPLOAD_CMD=""
fi

if [ -n "${UPLOAD_CMD:-}" ]; then
    ${UPLOAD_CMD} ${UPLOAD_SCRIPT} \
        --tracking-uri  "${UPLOAD_URI}" \
        --experiment    "${NF_EXPERIMENT}" \
        --run-name      "${RUN_NAME}" \
        --pipeline-info "${UPLOAD_PIPELINE_INFO}"
    echo "✓ Listo. Consulta los reportes en: ${MLFLOW_URI}"
fi

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
