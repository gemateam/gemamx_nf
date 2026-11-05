#!/usr/bin/env bash
# =============================================================================
# run_pipeline.sh — wrapper de ejecución de gemamx_nf
#
# Ejecuta el pipeline Nextflow. La publicación (archivo en runs/<runName>/,
# promoción atómica de data/ y reinicio de la webapp) la hace el propio
# pipeline desde workflow.onComplete: ver docs/ALMACENAMIENTO.md §4.
# Tras la corrida, el wrapper reintenta en primer plano la subida de los
# reportes HTML (report, timeline, dag) al run padre en MLflow.
#
# Uso:
#   bash run_pipeline.sh [opciones de nextflow]
#
# Ejemplos:
#   bash run_pipeline.sh -profile docker,gemamx-net,test
#   bash run_pipeline.sh -profile docker,gemamx-net,test -resume
#
# Variables de entorno opcionales:
#   MLFLOW_URI      URI del servidor MLflow  (default: http://localhost:5000)
#   NF_OUTDIR       Directorio de salida     (default: results)
#   NF_EXPERIMENT   Experimento en MLflow    (default: GEMAMX-V1-NF)
# =============================================================================
set -euo pipefail

MLFLOW_URI="${MLFLOW_URI:-http://localhost:5000}"
NF_OUTDIR="${NF_OUTDIR:-results}"
NF_EXPERIMENT="${NF_EXPERIMENT:-GEMAMX-V1-NF}"

# -stub-run no ejecuta nada real: los JSON son placeholders. El pipeline no
# archiva la corrida, no entra en runs/index.json y no promueve data/.
STUB_RUN=0
for arg in "$@"; do
    if [[ "${arg}" == "-stub-run" || "${arg}" == "-stub" ]]; then
        STUB_RUN=1
    fi
done

# Detectar el outdir efectivo desde los args del usuario (--outdir <valor>).
# Si no se especifica, usa NF_OUTDIR. El perfil 'test' ya apunta a 'results'
# en nextflow.config, así que no hace falta caso especial aquí.
EFFECTIVE_OUTDIR="${NF_OUTDIR}"
for i in "$@"; do
    if [[ "${PREV_ARG:-}" == "--outdir" ]]; then
        EFFECTIVE_OUTDIR="${i}"
    fi
    PREV_ARG="${i}"
done

PIPELINE_INFO="${EFFECTIVE_OUTDIR}/pipeline_info"
echo "▶ Outdir efectivo   : ${EFFECTIVE_OUTDIR}"
echo "▶ Reportes HTML en  : ${PIPELINE_INFO}"

# ---------------------------------------------------------------------------
# 1. Ejecutar pipeline Nextflow
# ---------------------------------------------------------------------------
echo "▶ Iniciando pipeline..."
if ! nextflow run . \
    -with-report   "${PIPELINE_INFO}/report.html" \
    -with-timeline "${PIPELINE_INFO}/timeline.html" \
    -with-dag      "${PIPELINE_INFO}/dag.html" \
    "$@"; then
    echo "✗ Pipeline terminó con error. No se suben reportes."
    exit 1
fi

echo "✓ Pipeline completado."

if [ "${STUB_RUN}" -eq 1 ]; then
    echo "▶ -stub-run: no se archiva la corrida, no se actualiza runs/index.json"
    echo "  (el contrato vigente en ${EFFECTIVE_OUTDIR}/data no se ha tocado)"
    exit 0
fi

# ---------------------------------------------------------------------------
# 2. Obtener el runName de la última corrida desde el log de Nextflow
# ---------------------------------------------------------------------------
# Nextflow escribe en .nextflow.log líneas como:
#   [main] INFO nextflow.Session - Run name: friendly_swanson
RUN_NAME=$(sed -n 's/.*Run name: //p' .nextflow.log 2>/dev/null | tail -1)

if [ -z "${RUN_NAME}" ]; then
    echo "WARN: no se pudo extraer el run name del log. Sube los reportes manualmente:"
    echo ""
    echo "  # Si mlflow está instalado en el host:"
    echo "  python3 bin/upload_nf_reports.py \\"
    echo "    --tracking-uri ${MLFLOW_URI} \\"
    echo "    --experiment   ${NF_EXPERIMENT} \\"
    echo "    --run-name     <run_name> \\"
    echo "    --pipeline-info ${PIPELINE_INFO}"
    echo ""
    echo "  # Si no (usar Docker con la red de este proyecto):"
    echo "  docker run --rm --network gemamx_net \\"
    echo "    -v \$(realpath ${PIPELINE_INFO}):/nf_reports:ro \\"
    echo "    -v \$(realpath bin):/workspace/bin:ro \\"
    echo "    gemamx-cpu:1.0.0 python3 /workspace/bin/upload_nf_reports.py \\"
    echo "    --tracking-uri http://gemamx_mlflow:5000 \\"
    echo "    --experiment   ${NF_EXPERIMENT} \\"
    echo "    --run-name     <run_name> \\"
    echo "    --pipeline-info /nf_reports"
    exit 0
fi

echo "▶ Run name detectado: ${RUN_NAME}"

# ---------------------------------------------------------------------------
# 3. Subir reportes HTML al run padre en MLflow
# ---------------------------------------------------------------------------
# upload_nf_reports.py requiere mlflow. En el host suele no estar instalado;
# en ese caso se corre dentro de gemamx-cpu:1.0.0 vía Docker, en la red
# correcta según el perfil activo.
# ---------------------------------------------------------------------------
echo "▶ Subiendo reportes HTML a MLflow..."

if python3 -c "import mlflow" 2>/dev/null; then
    # mlflow disponible en el host
    python3 bin/upload_nf_reports.py \
        --tracking-uri  "${MLFLOW_URI}" \
        --experiment    "${NF_EXPERIMENT}" \
        --run-name      "${RUN_NAME}" \
        --pipeline-info "${PIPELINE_INFO}"
    echo "✓ Listo. Consulta los reportes en: ${MLFLOW_URI}"
else
    echo "  (mlflow no disponible en host — usando gemamx-cpu:1.0.0 vía Docker)"

    # Red del stack de este repo (docker-compose up).
    DOCKER_NET="gemamx_net"
    DOCKER_URI="http://gemamx_mlflow:5000"

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
fi

# ---------------------------------------------------------------------------
# 4. Asegurar que la webapp está levantada
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
else
    echo "INFO: Docker no disponible — levanta la webapp manualmente:"
    echo "  docker compose up -d webapp"
fi
