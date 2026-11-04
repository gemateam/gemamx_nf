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

# -stub-run no ejecuta nada real: los JSON son placeholders. No debe archivarse
# como corrida ni entrar en runs/index.json (PUBLISH tampoco publica en data/).
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
nextflow run . \
    -with-report   "${PIPELINE_INFO}/report.html" \
    -with-timeline "${PIPELINE_INFO}/timeline.html" \
    -with-dag      "${PIPELINE_INFO}/dag.html" \
    "$@"

NF_EXIT=$?

if [ $NF_EXIT -ne 0 ]; then
    echo "✗ Pipeline terminó con error (código ${NF_EXIT}). No se suben reportes."
    exit "${NF_EXIT}"
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
RUN_NAME=$(grep -o "Run name: [a-z_]*" .nextflow.log 2>/dev/null | tail -1 | awk '{print $NF}')

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
# 3. Archivar corrida y actualizar índice de corridas históricas
# ---------------------------------------------------------------------------
# Nextflow publica <outdir>/data/ y <outdir>/run_manifest.json via publishDir.
# Aquí:
#   a) Copiamos data/ → runs/<runName>/data/  (archive inmutable)
#   b) Copiamos run_manifest.json → runs/<runName>/run_manifest.json
#   c) Actualizamos runs/index.json con la entrada de esta corrida
# ---------------------------------------------------------------------------
DATA_DIR="${EFFECTIVE_OUTDIR}/data"
MANIFEST_PATH="${EFFECTIVE_OUTDIR}/run_manifest.json"
RUN_ARCHIVE="${EFFECTIVE_OUTDIR}/runs/${RUN_NAME}"
INDEX_PATH="${EFFECTIVE_OUTDIR}/runs/index.json"

echo "▶ Archivando corrida en runs/${RUN_NAME}..."
if [ -d "${DATA_DIR}" ] && [ -f "${MANIFEST_PATH}" ]; then
    mkdir -p "${RUN_ARCHIVE}"
    # Copiar contrato de datos (solo si el archive no existe ya)
    if [ ! -d "${RUN_ARCHIVE}/data" ]; then
        cp -r "${DATA_DIR}" "${RUN_ARCHIVE}/data"
    fi
    cp "${MANIFEST_PATH}" "${RUN_ARCHIVE}/run_manifest.json"
    # run_manifest también dentro de data/ para que la webapp lo encuentre
    # cuando BASE_PATH = "runs/<name>/data"
    cp "${MANIFEST_PATH}" "${RUN_ARCHIVE}/data/run_manifest.json"
    echo "  ✓ ${RUN_ARCHIVE}"
else
    echo "  WARN: data/ o run_manifest.json no encontrados en ${EFFECTIVE_OUTDIR}"
fi

echo "▶ Actualizando índice de corridas..."
if [ -f "${MANIFEST_PATH}" ]; then
    export EFFECTIVE_OUTDIR RUN_NAME
    python3 - << 'PYEOF'
import json, os, pathlib

outdir      = os.environ.get("EFFECTIVE_OUTDIR", "results")
run_name    = os.environ.get("RUN_NAME", "")
index_path  = pathlib.Path(outdir) / "runs" / "index.json"
manifest_p  = pathlib.Path(outdir) / "run_manifest.json"

try:
    manifest = json.loads(manifest_p.read_text())
except Exception:
    manifest = {}

index = []
if index_path.is_file():
    try:
        index = json.loads(index_path.read_text()) or []
    except Exception:
        index = []

entry = {
    "run_name":     run_name,
    "published_at": manifest.get("published_at", ""),
    "git_commit":   manifest.get("git_commit", "")[:7],
    "path":         f"runs/{run_name}/data",
}
index = [e for e in index if e.get("run_name") != run_name]
index.insert(0, entry)
index_path.parent.mkdir(parents=True, exist_ok=True)
index_path.write_text(json.dumps(index, indent=2))
print(f"  índice actualizado: {len(index)} corrida(s)")
PYEOF
else
    echo "  WARN: manifest no encontrado en ${MANIFEST_PATH} — índice no actualizado"
fi

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
