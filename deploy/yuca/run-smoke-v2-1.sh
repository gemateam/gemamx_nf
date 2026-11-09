#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE_DIR="${YUCA_BASE_DIR:?Define YUCA_BASE_DIR según las instrucciones de tu sitio}"

cd "${ROOT}"

# Load the validated Apptainer module when the shell has not loaded it already.
if ! command -v apptainer >/dev/null 2>&1; then
    if [[ -f /etc/profile ]]; then
        # shellcheck disable=SC1091
        set +u
        source /etc/profile
        set -euo pipefail
    fi
    if type module >/dev/null 2>&1; then
        module load apptainer/1.5.3-3.el8
    fi
fi

bash deploy/yuca/preflight.sh

stub_run=0
MLFLOW_ENABLED="${YUCA_MLFLOW_ENABLED:-false}"
case "${MLFLOW_ENABLED}" in
    true|false) ;;
    *) printf 'YUCA_MLFLOW_ENABLED debe ser true o false.\n' >&2; exit 2 ;;
esac

for argument in "$@"; do
    if [[ "${argument}" == "-stub-run" ]]; then
        stub_run=1
    fi
done

if [[ "${stub_run}" -eq 0 && "${MLFLOW_ENABLED}" == "true" ]]; then
    if [[ -z "${MLFLOW_TRACKING_URI:-}" ]]; then
        printf 'Define MLFLOW_TRACKING_URI a un servidor alcanzable desde Yuca antes de la corrida.\n' >&2
        printf 'No se almacenan credenciales en este script; usa el mecanismo aprobado por ACARUS.\n' >&2
        exit 4
    fi
    export MLFLOW_HOST_URI="${MLFLOW_HOST_URI:-${MLFLOW_TRACKING_URI}}"
    python3 - "${MLFLOW_TRACKING_URI%/}/health" <<'PY'
import sys
import urllib.request

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=8) as response:
        if response.status != 200:
            raise SystemExit(f"MLflow healthcheck devolvió HTTP {response.status}: {url}")
except Exception as exc:
    raise SystemExit(f"MLflow no es alcanzable desde este nodo ({url}): {exc}")
print(f"MLflow accesible: {url}")
PY
fi

RUN_NAME="yuca_smoke_v2_1_$(date -u +%Y%m%d_%H%M%S)"
printf 'Ejecutando %s en SLURM/Apptainer; resultados aislados en results/smoke_v2_1.\n' "${RUN_NAME}"
NEXTFLOW_ARGS=(
    run main_v2_1.nf
    -profile romero-v2,v2_1,smoke-v2-1,yuca
    -c deploy/yuca/resources.config
    -name "${RUN_NAME}"
    --mlflow_enabled "${MLFLOW_ENABLED}"
    -resume
    "$@"
)
nextflow "${NEXTFLOW_ARGS[@]}"
