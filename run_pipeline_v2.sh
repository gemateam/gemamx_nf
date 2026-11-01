#!/usr/bin/env bash
# =============================================================================
# run_pipeline_v2.sh — wrapper para el pipeline V2 (Romero-Córdoba 2021 HM)
#
# Ejecuta main_v2.nf y sube los reportes HTML al run padre en MLflow.
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
PIPELINE_INFO="${NF_OUTDIR}/pipeline_info"

# Generar un runName único si no se pasa -name explícito en argumentos
CUSTOM_NAME=""
for arg in "$@"; do
    if [[ "${PREV_ARG:-}" == "-name" ]]; then
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
nextflow run main_v2.nf \
    -profile docker,'romero-v2' \
    "${NAME_ARGS[@]}" \
    -with-report   "${PIPELINE_INFO}/report.html" \
    -with-timeline "${PIPELINE_INFO}/timeline.html" \
    -with-dag      "${PIPELINE_INFO}/dag.html" \
    "$@"

NF_EXIT=$?
if [ $NF_EXIT -ne 0 ]; then
    echo "✗ Pipeline V2 terminó con error (código ${NF_EXIT})."
    exit "${NF_EXIT}"
fi
echo "✓ Pipeline V2 completado."

# ---------------------------------------------------------------------------
# 2. Archivar corrida
# ---------------------------------------------------------------------------
DATA_DIR="${NF_OUTDIR}/data"
MANIFEST_PATH="${NF_OUTDIR}/run_manifest.json"
RUN_ARCHIVE="${NF_OUTDIR}/runs/${RUN_NAME}"

echo "▶ Archivando corrida en runs/${RUN_NAME}..."
if [ -d "${DATA_DIR}" ] && [ -f "${MANIFEST_PATH}" ]; then
    mkdir -p "${RUN_ARCHIVE}"
    if [ ! -d "${RUN_ARCHIVE}/data" ]; then
        cp -r "${DATA_DIR}" "${RUN_ARCHIVE}/data"
    fi
    cp "${MANIFEST_PATH}" "${RUN_ARCHIVE}/run_manifest.json"
    cp "${MANIFEST_PATH}" "${RUN_ARCHIVE}/data/run_manifest.json"
    echo "  ✓ ${RUN_ARCHIVE}"
else
    echo "  WARN: data/ o run_manifest.json no encontrados."
fi

echo "▶ Actualizando índice de corridas..."
export NF_OUTDIR RUN_NAME
python3 - << 'PYEOF'
import json, os, pathlib

outdir      = os.environ.get("NF_OUTDIR", "results")
run_name    = os.environ.get("RUN_NAME", "romero_v2")
index_path  = pathlib.Path(outdir) / "runs" / "index.json"
manifest_p  = pathlib.Path(outdir) / "run_manifest.json"

try:
    manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
except Exception:
    manifest = {}

index = []
if index_path.is_file():
    try:
        index = json.loads(index_path.read_text(encoding="utf-8")) or []
    except Exception:
        index = []

entry = {
    "run_name":          run_name,
    "published_at":      manifest.get("published_at", ""),
    "git_commit":        manifest.get("git_commit", "")[:7],
    "pipeline_version":  manifest.get("pipeline_version", "GEMAMX-V2-ROMERO"),
    "path":              f"runs/{run_name}/data",
}

index = [e for e in index if e.get("run_name") != run_name]
index.insert(0, entry)
index_path.parent.mkdir(parents=True, exist_ok=True)
index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
print(f"  índice actualizado: {len(index)} corrida(s)")
PYEOF

# ---------------------------------------------------------------------------
# 3. Subir reportes HTML al run padre en MLflow
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
    docker run --rm \
        --network gemacont_default \
        -v "${ABS_PIPELINE_INFO}:/nf_reports:ro" \
        -v "$(realpath bin):/workspace/bin:ro" \
        gemamx-cpu:1.0.0 \
        python3 /workspace/bin/upload_nf_reports.py \
            --tracking-uri  "http://mlflow:5000" \
            --experiment    "${NF_EXPERIMENT}" \
            --run-name      "${RUN_NAME}" \
            --pipeline-info /nf_reports
    echo "✓ Listo. Ver en: ${MLFLOW_URI}"
fi

# ---------------------------------------------------------------------------
# 4. Levantar webapp
# ---------------------------------------------------------------------------
echo "▶ Levantando webapp..."
if command -v docker &>/dev/null && [ -f docker-compose.yml ]; then
    docker compose up -d webapp 2>&1
    echo "✓ Webapp disponible en: http://localhost:8080"
fi
