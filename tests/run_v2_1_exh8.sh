#!/usr/bin/env bash
# =============================================================================
# Validación de main_v2_1.nf con exhaustiveness=8 (paso 1 del análisis V2.0/V2.1).
#
#   bash tests/run_v2_1_exh8.sh            # corrida real, aislada de producción
#   bash tests/run_v2_1_exh8.sh -stub-run  # solo valida canales (sin Docker)
#   bash tests/run_v2_1_exh8.sh -resume    # reanuda la última corrida de este script
#
# Qué hace:
#   1. Corre main_v2_1.nf (perfil v2_1: bolsillo ATP, solo pares fármaco-diana)
#      con exhaustiveness=8 y las 3 variantes de la prueba de humo.
#   2. Aísla outdir, workDir y experimento MLflow para NO tocar results/data
#      (contrato vigente) ni el caché de producción.
#   3. Genera los reportes HTML de Nextflow (report, timeline, dag + trace.tsv)
#      en <outdir>/pipeline_info/ y los sube al run padre de MLflow.
#   4. Analiza el resultado: puntajes Vina positivos (poses fallidas), mejor
#      fármaco on-target vs control, RMSD/pLDDT y Δ(MUT−WT).
#
# Variables opcionales:
#   MLFLOW_EXPERIMENT  (def. GEMAMX-V2_1-EXH8)
#   MAX_VARIANTS       (def. 3)
#   EXHAUSTIVENESS     (def. 8)
#   VINA_PROC_TIME     (def. 4h)    límite de Nextflow por tarea RUN_VINA
#   VINA_TIMEOUT_SEC   (def. 12600) límite interno de AutoDock Vina por par
#   MLFLOW_HOST_URI    (def. http://localhost:5000)
# =============================================================================
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

TAG="v2_1_exh8"
OUT="results/${TAG}"
WORK="${HOME}/gemamx-work-${TAG}"
EXPERIMENT="${MLFLOW_EXPERIMENT:-GEMAMX-V2_1-EXH8}"
MAX_VARIANTS="${MAX_VARIANTS:-3}"
EXHAUSTIVENESS="${EXHAUSTIVENESS:-8}"
HOST_URI="${MLFLOW_HOST_URI:-http://localhost:5000}"
# Con exhaustiveness=8 un par Vina puede pasar de 30 min (límite por defecto de
# RUN_VINA en nextflow.config y vina_timeout_sec=1800 del perfil romero-v2).
# VINA_TIMEOUT_SEC (límite interno de Vina) debe ser menor que VINA_PROC_TIME.
VINA_PROC_TIME="${VINA_PROC_TIME:-4h}"
VINA_TIMEOUT_SEC="${VINA_TIMEOUT_SEC:-12600}"
DOCKER_URI="http://gemamx_mlflow:5000"
DOCKER_NET="gemamx_net"
IMAGE="gemamx-cpu:1.0.0"
RUN_NAME="${TAG}_$(date +%Y%m%d_%H%M%S)"

STUB=0
for arg in "$@"; do [[ "$arg" == "-stub-run" ]] && STUB=1; done

# ── Comprobaciones previas ───────────────────────────────────────────────────
command -v nextflow >/dev/null 2>&1 || { echo "✗ nextflow no está en el PATH (¿WSL?)." >&2; exit 1; }
command -v docker   >/dev/null 2>&1 || { echo "✗ docker no está disponible en este entorno." >&2; exit 1; }

if [[ "$STUB" -eq 0 ]]; then
    if curl -fsS --max-time 5 "${HOST_URI}/health" >/dev/null 2>&1; then
        echo "  ✓ MLflow responde en ${HOST_URI}"
    else
        echo "  ⚠ MLflow no responde en ${HOST_URI}: sube el stack con 'docker compose up -d'." >&2
        echo "    La corrida seguirá, pero LOG_MLFLOW y la subida de reportes pueden fallar." >&2
    fi
fi

# ── Contrato vigente: huella antes de correr ─────────────────────────────────
CONTRACT=results/data/run_manifest.json
before=""
[[ -f "$CONTRACT" ]] && before=$(sha256sum "$CONTRACT" | cut -d' ' -f1)

mkdir -p "${OUT}/pipeline_info"
START_EPOCH=$(date +%s)

# Config extra solo para esta corrida: sube el límite de tiempo de RUN_VINA sin
# tocar nextflow.config (el valor por defecto es 30m y mata los pares lentos).
EXTRA_CONF="$(mktemp --suffix=.config)"
trap 'rm -f "${EXTRA_CONF}"' EXIT
cat > "${EXTRA_CONF}" <<EOF
process {
    withName: 'RUN_VINA' { time = '${VINA_PROC_TIME}' }
}
EOF

echo "▶ main_v2_1.nf — run: ${RUN_NAME}"
echo "  outdir: ${OUT} · work: ${WORK}"
echo "  exhaustiveness=${EXHAUSTIVENESS} · max_variants=${MAX_VARIANTS} · MLflow: ${EXPERIMENT}"
echo "  RUN_VINA: límite Nextflow ${VINA_PROC_TIME} · timeout Vina ${VINA_TIMEOUT_SEC}s"

# Los reportes HTML (report, timeline, dag) y trace.tsv ya están activos en
# nextflow.config y se escriben en <outdir>/pipeline_info/.
nextflow run main_v2_1.nf \
    -profile docker,romero-v2,v2_1 \
    -name "${RUN_NAME}" \
    -work-dir "${WORK}" \
    -c "${EXTRA_CONF}" \
    --outdir "${OUT}" \
    --exhaustiveness "${EXHAUSTIVENESS}" \
    --vina_timeout_sec "${VINA_TIMEOUT_SEC}" \
    --max_variants "${MAX_VARIANTS}" \
    --site_on_missing centroid \
    --publish_run_archive false \
    --mlflow_experiment "${EXPERIMENT}" \
    "$@"

# ── Aislamiento del contrato vigente ─────────────────────────────────────────
echo "▶ Verificando aislamiento del contrato vigente..."
after=""
[[ -f "$CONTRACT" ]] && after=$(sha256sum "$CONTRACT" | cut -d' ' -f1)
if [[ "$before" != "$after" ]]; then
    echo "✗ results/data/run_manifest.json cambió: la corrida contaminó producción." >&2
    exit 1
fi
echo "  ✓ results/data intacto"

if [[ "$STUB" -eq 1 ]]; then
    echo "✓ stub-run completado (no se analizan resultados ni se suben reportes)."
    exit 0
fi

# ── Reportes HTML → MLflow ───────────────────────────────────────────────────
# workflow.onComplete ya lanzó este mismo hook en segundo plano, pero puede morir
# si la terminal se cierra. Esta invocación en primer plano lo garantiza; el
# hook es idempotente (candado + marca .uploaded.<run>), así que no duplica.
echo "▶ Subiendo reportes HTML de Nextflow a MLflow..."
bash bin/nf_reports_hook.sh \
    --outdir "${OUT}" \
    --run-name "${RUN_NAME}" \
    --experiment "${EXPERIMENT}" \
    --host-uri "${HOST_URI}" \
    --docker-uri "${DOCKER_URI}" \
    --docker-network "${DOCKER_NET}" \
    --image "${IMAGE}" \
    --bin bin \
    --since "${START_EPOCH}"

INFO="${OUT}/pipeline_info"
echo "  Reportes generados:"
for f in report.html timeline.html dag.html trace.tsv; do
    if [[ -s "${INFO}/${f}" ]]; then
        printf '    ✓ %-14s %s bytes\n' "$f" "$(stat -c %s "${INFO}/${f}")"
    else
        printf '    ✗ %-14s ausente o vacío\n' "$f"
    fi
done
echo "  Últimas líneas de ${INFO}/upload.log:"
tail -n 4 "${INFO}/upload.log" 2>/dev/null | sed 's/^/    /' || true

UPLOAD_OK=1
if [[ -e "${INFO}/.uploaded.${RUN_NAME}" ]]; then
    echo "  ✓ Reportes subidos a MLflow (marca .uploaded.${RUN_NAME})"
else
    UPLOAD_OK=0
    echo "  ✗ No hay marca .uploaded.${RUN_NAME}: la subida no se completó." >&2
    echo "    Revisa ${INFO}/upload.log y que el stack de MLflow esté arriba." >&2
fi

# ── Análisis de resultados ───────────────────────────────────────────────────
echo "▶ Analizando resultados (${OUT}/data)..."
python3 - "${OUT}" <<'PY' | tee "${INFO}/analisis.txt"
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
data = out / "data"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


top = load(data / "top_variants.json")
metrics = load(data / "structural_metrics.json")
manifest = load(data / "manifest_structures.json")
aff = load(data / "docking" / "vina_affinities.json")
roles = load(data / "docking" / "vina_roles.json")


def ok(v):
    """Puntaje Vina utilizable: numérico y ≤ 0 (los positivos son poses fallidas)."""
    return isinstance(v, (int, float)) and v <= 0


print("== 1. Estructura: RMSD y pLDDT ==")
for row in top:
    vid = f"{row['hugo_symbol']}_{row['protein_change']}"
    m = metrics.get(vid)
    if not m:
        print(f"  ✗ {vid}: sin métricas")
        continue
    print(f"  {vid:<16} RMSD global {m.get('rmsd_global')} Å · sitio activo "
          f"{m.get('rmsd_active')} Å · pLDDT WT {m.get('wt_plddt')} / MUT {m.get('mut_plddt')}")

print("\n== 2. Puntajes Vina positivos (poses fallidas; repetir/descartar) ==")
bad = [(t, d, v) for t, s in aff.items() for d, v in s.items()
       if isinstance(v, (int, float)) and v > 0]
if bad:
    for t, d, v in bad:
        print(f"  ⚠ {t} × {d}: {v:+.3f}")
else:
    print("  ✓ ninguno")

print("\n== 3. Mejor on-target vs mejor control (kcal/mol, más negativo = mejor) ==")
for target, scores in aff.items():
    info = roles.get(target, {})
    on = {d: v for d, v in scores.items() if ok(v) and info.get(d, {}).get("role") == "on_target"}
    off = {d: v for d, v in scores.items()
           if ok(v) and info.get(d, {}).get("role") == "off_target_control"}
    best_on = min(on.items(), key=lambda kv: kv[1]) if on else None
    best_off = min(off.items(), key=lambda kv: kv[1]) if off else None
    covered = all(i.get("site_covered") for i in info.values()) if info else False
    line = f"  {target:<16}"
    line += f" on-target: {best_on[0]} {best_on[1]:.3f}" if best_on else " on-target: —"
    line += f" | control: {best_off[0]} {best_off[1]:.3f}" if best_off else " | control: —"
    print(line + ("" if covered else "  [bolsillo NO cubierto]"))
    if best_on and best_off and best_off[1] < best_on[1]:
        print("      ⚠ un control supera al mejor on-target: el ranking no discrimina por rol")

print("\n== 4. Δ(MUT − WT) por fármaco (negativo = la mutante une mejor) ==")
any_delta = False
for row in top:
    gene, pc = row["hugo_symbol"], row["protein_change"]
    vid, canon, wt_key = f"{gene}_{pc}", f"{gene}_WT", f"{gene}_WT_{pc}"
    # Solo se dockea el WT canónico por gen (alias <GEN>_WT).
    if manifest.get(canon) != manifest.get(wt_key) or canon not in aff or vid not in aff:
        print(f"  – {vid}: sin WT dockeado propio (no comparable)")
        continue
    print(f"  {vid}")
    for drug in sorted(set(aff[vid]) & set(aff[canon])):
        mut, wt = aff[vid][drug], aff[canon][drug]
        if ok(mut) and ok(wt):
            any_delta = True
            print(f"    {drug:<13} MUT {mut:8.3f}  WT {wt:8.3f}  Δ {mut - wt:+.3f}")
        else:
            print(f"    {drug:<13} descartado (puntaje positivo en MUT o WT)")
if not any_delta:
    print("  (sin pares comparables)")
PY

echo
echo "✓ Corrida ${RUN_NAME} terminada. Salida en ${OUT}/ · análisis en ${INFO}/analisis.txt"
[[ "$UPLOAD_OK" -eq 1 ]] || exit 1
