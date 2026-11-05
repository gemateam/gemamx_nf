#!/usr/bin/env bash
# =============================================================================
# Hook de workflow.onComplete: promueve el contrato vigente y archiva la corrida.
#
# Corre en el host, no en un contenedor: la promoción es un par de `rename`
# sobre el outdir, y un proceso en Docker no ve esas rutas. Lo llama
# `workflow.onComplete` de main.nf, main_v2.nf y main_v2_1.nf.
#
#   bash bin/publish_contract_hook.sh --outdir results --run-name <name> \
#        --archive true --restart-container gemamx_webapp --bin bin
#
# Nunca tumba la corrida: si no puede promover, deja data/ con la corrida
# anterior y sale con código 1 para que Nextflow lo registre como error.
# =============================================================================
set -uo pipefail

OUTDIR="results"
RUN_NAME=""
ARCHIVE="true"
RESTART=""
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --outdir)   OUTDIR="$2";   shift 2 ;;
        --run-name) RUN_NAME="$2"; shift 2 ;;
        --archive)  ARCHIVE="$2";  shift 2 ;;
        --restart-container) RESTART="$2"; shift 2 ;;
        --bin)      BIN_DIR="$2";  shift 2 ;;
        *) echo "argumento desconocido: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "${RUN_NAME}" ]]; then
    echo "ERROR: falta --run-name; no se promueve el contrato." >&2
    exit 1
fi

PY=""
for candidate in python3 python; do
    if command -v "${candidate}" >/dev/null 2>&1; then PY="${candidate}"; break; fi
done

if [[ -z "${PY}" ]]; then
    echo "ERROR: no hay python3 en el host; data/ sigue con la corrida anterior." >&2
    echo "       Repite a mano: python3 bin/publish_contract.py --outdir '${OUTDIR}' \\" >&2
    echo "         --run-name '${RUN_NAME}' --archive ${ARCHIVE}" >&2
    exit 1
fi

args=("${BIN_DIR}/publish_contract.py" --outdir "${OUTDIR}" --run-name "${RUN_NAME}"
      --archive "${ARCHIVE}")
if [[ -n "${RESTART}" ]]; then
    args+=(--restart-container "${RESTART}")
fi
exec "${PY}" "${args[@]}"
