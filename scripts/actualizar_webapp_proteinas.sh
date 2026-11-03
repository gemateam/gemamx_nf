#!/usr/bin/env bash
# =============================================================================
# Actualiza la webapp SOLO con las proteínas (modelos AlphaFold DB externos).
# No toca el pipeline ni results/.
#
#   bash scripts/actualizar_webapp_proteinas.sh
#   TOP=40 bash scripts/actualizar_webapp_proteinas.sh              # más genes
#   EXTRA_GENES=BRCA2,KMT2C bash scripts/actualizar_webapp_proteinas.sh
#   DATA_DIR=results/runs/<corrida>/data bash scripts/actualizar_webapp_proteinas.sh
#   PRUNE=0 bash scripts/actualizar_webapp_proteinas.sh             # no borrar CIF huérfanos
#
# Pasos:
#   1. Descarga de AlphaFold DB los TOP genes más mutados que la corrida no trae
#      con estructura (los que ya están descargados se reutilizan).
#   2. Descarga además EXTRA_GENES, si se indican.
#   3. Borra de structures/external/ los CIF que no estén en index.json (PRUNE=1).
#   4. Reconstruye y reinicia solo el servicio webapp (código JS + volumen).
#   5. Verifica que nginx sirva external/index.json y un modelo .cif.
#
# Variables: TOP (def. 20) · DATA_DIR (def. results/data) · EXTRA_GENES · PRUNE (def. 1)
#            WEBAPP_URL (def. http://localhost:8080)
# =============================================================================
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

TOP="${TOP:-20}"
DATA_DIR="${DATA_DIR:-results/data}"
EXTRA_GENES="${EXTRA_GENES:-}"
PRUNE="${PRUNE:-1}"
WEBAPP_URL="${WEBAPP_URL:-http://localhost:8080}"
OUT_DIR="structures/external"

command -v python3 >/dev/null 2>&1 || { echo "✗ python3 no está disponible (usa WSL)." >&2; exit 1; }
command -v docker  >/dev/null 2>&1 || { echo "✗ docker no está disponible en este entorno." >&2; exit 1; }
[[ -f "${DATA_DIR}/raw_mutations.json" ]] || { echo "✗ No existe ${DATA_DIR}/raw_mutations.json" >&2; exit 1; }

mkdir -p "${OUT_DIR}"

# ── 1. Genes más mutados sin estructura propia ───────────────────────────────
echo "▶ [1/4] Descargando modelos AlphaFold DB (top ${TOP} de ${DATA_DIR})"
python3 bin/fetch_external_structures.py --from-data "${DATA_DIR}" --top "${TOP}"

# ── 2. Genes adicionales ─────────────────────────────────────────────────────
if [[ -n "${EXTRA_GENES}" ]]; then
    echo "▶ Genes adicionales: ${EXTRA_GENES}"
    python3 bin/fetch_external_structures.py --genes "${EXTRA_GENES}"
fi

# ── 3. Limpiar CIF que no están en el índice ─────────────────────────────────
if [[ "${PRUNE}" == "1" ]]; then
    echo "▶ [2/4] Limpiando CIF fuera del índice"
    python3 bin/fetch_external_structures.py --prune
else
    echo "▶ [2/4] PRUNE=0: no se borra nada"
fi

# ── 4. Reconstruir solo la webapp ────────────────────────────────────────────
echo "▶ [3/4] Reconstruyendo el servicio webapp"
docker compose up -d --build webapp

# ── 5. Verificación ──────────────────────────────────────────────────────────
echo "▶ [4/4] Verificando ${WEBAPP_URL}"
ready=0
for _ in $(seq 1 20); do
    if curl -fsS --max-time 3 "${WEBAPP_URL}/health" >/dev/null 2>&1; then ready=1; break; fi
    sleep 2
done
if [[ "$ready" -ne 1 ]]; then
    echo "  ✗ La webapp no responde en ${WEBAPP_URL}/health (revisa: docker logs gemamx_webapp)" >&2
    exit 1
fi

INDEX="$(curl -fsS --max-time 10 "${WEBAPP_URL}/external/index.json")" || {
    echo "  ✗ nginx no sirve /external/index.json: el volumen no se montó." >&2
    echo "    Comprueba: docker exec gemamx_webapp ls /usr/share/nginx/html/external" >&2
    exit 1
}
N_GENES="$(printf '%s' "${INDEX}" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
FIRST_FILE="$(printf '%s' "${INDEX}" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(iter(d.values()))["file"] if d else "")')"
echo "  ✓ /external/index.json sirve ${N_GENES} gen(es)"

if [[ -n "${FIRST_FILE}" ]]; then
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "${WEBAPP_URL}/external/${FIRST_FILE}")"
    if [[ "${code}" == "200" ]]; then
        echo "  ✓ /external/${FIRST_FILE} responde 200"
    else
        echo "  ✗ /external/${FIRST_FILE} respondió ${code}" >&2
        exit 1
    fi
fi

echo
echo "✓ Webapp actualizada. Abre ${WEBAPP_URL} y recarga con Ctrl+F5."
du -sh "${OUT_DIR}" | sed 's/^/  Tamaño de structures\/external: /'
