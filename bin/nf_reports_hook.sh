#!/usr/bin/env bash
# =============================================================================
# nf_reports_hook.sh — sube los reportes HTML de Nextflow al run padre de MLflow.
#
# Lo lanza `workflow.onComplete` de cada entrypoint (main.nf, main_v2.nf,
# main_v2_1.nf) desacoplado de la terminal (setsid), y los wrappers de prueba
# (tests/run_smoke_*.sh) lo vuelven a invocar en primer plano al terminar. Es
# idempotente: si los reportes del run ya se subieron, no hace nada.
#
# Por qué dos disparos: Nextflow escribe los HTML DESPUÉS de onComplete, así que
# el envío no puede ser síncrono ahí; y un proceso en segundo plano puede morir
# si la terminal que lanzó `bash script.sh` (p. ej. PowerShell -> WSL) termina
# antes de que el hook suba nada. El disparo en primer plano lo garantiza.
#
# Corre en el host, fuera de Docker. Espera a que los HTML del run existan, estén
# estables y sean más recientes que --since (para no subir los de la corrida
# anterior: Nextflow los sobrescribe). Si el host no tiene mlflow, reintenta
# dentro del contenedor CPU en la red de docker-compose.
#
# Uso (lo construye el propio pipeline):
#   nf_reports_hook.sh --outdir results --run-name friendly_swanson \
#       --experiment GEMAMX-V2_1-ROMERO \
#       --host-uri http://localhost:5000 \
#       --docker-uri http://gemamx_mlflow:5000 --docker-network gemamx_net \
#       --image gemamx-cpu:1.0.0 --bin /ruta/al/repo/bin \
#       --since 1762050000            # epoch; solo reportes modificados desde ahí
#
# Salida: <outdir>/pipeline_info/upload.log (una línea por evento) y la marca
# <outdir>/pipeline_info/.uploaded.<run-name> cuando la subida fue exitosa.
# Nunca falla el pipeline: cualquier error se registra y termina con código 0.
# =============================================================================
set -uo pipefail

OUTDIR="results"
RUN_NAME=""
EXPERIMENT=""
HOST_URI="http://localhost:5000"
DOCKER_URI="http://gemamx_mlflow:5000"
DOCKER_NET="gemamx_net"
IMAGE="gemamx-cpu:1.0.0"
BIN_DIR="bin"
WAIT_SECS=300
SINCE=0
LOCK_WAIT_SECS=900

while [[ $# -gt 0 ]]; do
    case "$1" in
        --outdir)          OUTDIR="$2"; shift 2 ;;
        --run-name)        RUN_NAME="$2"; shift 2 ;;
        --experiment)      EXPERIMENT="$2"; shift 2 ;;
        --host-uri)        HOST_URI="$2"; shift 2 ;;
        --docker-uri)      DOCKER_URI="$2"; shift 2 ;;
        --docker-network)  DOCKER_NET="$2"; shift 2 ;;
        --image)           IMAGE="$2"; shift 2 ;;
        --bin)             BIN_DIR="$2"; shift 2 ;;
        --wait)            WAIT_SECS="$2"; shift 2 ;;
        --since)           SINCE="$2"; shift 2 ;;
        *) echo "argumento desconocido: $1" >&2; exit 0 ;;
    esac
done

INFO_DIR="${OUTDIR}/pipeline_info"
LOG="${INFO_DIR}/upload.log"
mkdir -p "${INFO_DIR}"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "${LOG}"; }

uploader="${BIN_DIR}/upload_nf_reports.py"
if [[ ! -f "${uploader}" ]]; then
    log "ERROR no existe ${uploader}; no se suben reportes"
    exit 0
fi
if [[ -z "${RUN_NAME}" || -z "${EXPERIMENT}" ]]; then
    log "ERROR faltan --run-name/--experiment; no se suben reportes"
    exit 0
fi

# ── Un solo envío por corrida ────────────────────────────────────────────────
# El disparo de onComplete y el del wrapper pueden coincidir: el segundo espera
# el candado y, si el primero ya subió, termina sin repetir. Si el primero murió,
# el candado se libera solo y el segundo hace el trabajo.
LOCK="${INFO_DIR}/.upload.lock"
MARK="${INFO_DIR}/.uploaded.${RUN_NAME}"
if command -v flock >/dev/null 2>&1 && (exec 9>"${LOCK}") 2>/dev/null; then
    exec 9>"${LOCK}"
    if ! flock -w "${LOCK_WAIT_SECS}" 9; then
        log "SKIP no se obtuvo el candado de subida en ${LOCK_WAIT_SECS}s (run=${RUN_NAME})"
        exit 0
    fi
fi
if [[ -e "${MARK}" ]]; then
    log "SKIP los reportes de ${RUN_NAME} ya se subieron"
    exit 0
fi

# ── Esperar a que Nextflow escriba los HTML ──────────────────────────────────
# Un reporte es válido si no está vacío y es más reciente que --since. report.html
# es el último grande: se espera a que su tamaño se estabilice para no subirlo a
# medio escribir.
mtime() { stat -c %Y "$1" 2>/dev/null || echo 0; }
fresh() { [[ -s "$1" ]] && (( $(mtime "$1") >= SINCE )); }

report="${INFO_DIR}/report.html"
waited=0
stable=0
last_size=-1
while (( waited < WAIT_SECS )); do
    if fresh "${report}"; then
        size=$(stat -c %s "${report}" 2>/dev/null || echo 0)
        if [[ "${size}" -eq "${last_size}" ]]; then
            stable=$((stable + 1))
            (( stable >= 2 )) && break
        else
            stable=0
        fi
        last_size="${size}"
    fi
    sleep 1
    waited=$((waited + 1))
done

if ! fresh "${report}"; then
    log "SKIP ${report} no apareció (o es anterior a --since=${SINCE}) tras ${WAIT_SECS}s (run=${RUN_NAME})"
    exit 0
fi

# timeline.html y dag.html se escriben justo después del report: hasta 20 s.
for ((i = 0; i < 20; i++)); do
    if fresh "${INFO_DIR}/timeline.html" && fresh "${INFO_DIR}/dag.html"; then
        break
    fi
    sleep 1
done
sleep 2

log "subiendo reportes (run=${RUN_NAME}, experiment=${EXPERIMENT})"

# ── Subida: host si tiene mlflow; si no, contenedor CPU ─────────────────────
if python3 -c "import mlflow" >/dev/null 2>&1; then
    if python3 "${uploader}" \
            --tracking-uri  "${HOST_URI}" \
            --experiment    "${EXPERIMENT}" \
            --run-name      "${RUN_NAME}" \
            --pipeline-info "${INFO_DIR}" >> "${LOG}" 2>&1; then
        touch "${MARK}"
        log "OK reportes subidos desde el host -> ${HOST_URI}"
    else
        log "ERROR falló upload_nf_reports.py en el host -> ${HOST_URI}"
    fi
    exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
    log "ERROR sin mlflow en el host y sin docker; reportes solo en ${INFO_DIR}"
    exit 0
fi

abs_info="$(realpath "${INFO_DIR}")"
abs_bin="$(realpath "${BIN_DIR}")"
if docker run --rm \
        --network "${DOCKER_NET}" \
        -v "${abs_info}:/nf_reports:ro" \
        -v "${abs_bin}:/workspace/bin:ro" \
        "${IMAGE}" \
        python3 /workspace/bin/upload_nf_reports.py \
            --tracking-uri  "${DOCKER_URI}" \
            --experiment    "${EXPERIMENT}" \
            --run-name      "${RUN_NAME}" \
            --pipeline-info /nf_reports >> "${LOG}" 2>&1; then
    touch "${MARK}"
    log "OK reportes subidos desde el contenedor -> ${DOCKER_URI}"
else
    log "ERROR falló upload_nf_reports.py en el contenedor -> ${DOCKER_URI}"
fi

exit 0
