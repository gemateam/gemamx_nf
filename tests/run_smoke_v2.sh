#!/usr/bin/env bash
# =============================================================================
# Prueba de humo de main_v2.nf (V2.0, intocable) — regresión.
#
#   bash tests/run_smoke_v2.sh            # corrida real, aislada
#   bash tests/run_smoke_v2.sh -stub-run  # solo valida canales y pares (sin Docker)
#
# Aislamiento (perfil `smoke`): outdir=results/smoke, workDir=~/gemamx-work-smoke,
# experimento MLflow GEMAMX-SMOKE. NO ejecuta el wrapper de archivo de corridas ni
# levanta la webapp, y verifica que results/data (contrato vigente) no cambió.
#
# Comprueba que V2.0 sigue comportándose como antes de V2.1:
#   - cada variante priorizada tiene RMSD;
#   - el manifest conserva un solo WT por gen (<GEN>_WT, sin sufijo de variante);
#   - no se generan artefactos de V2.1 (vina_roles.json).
#
# Con 2 variantes (PIK3CA_H1047R + AKT1_E17K) V2.0 funciona; la 3.ª
# (PIK3CA_E542K, ventana distinta) fallaría ALIGN_WT_MUT por el WT único por gen.
# Ese caso lo cubre tests/run_smoke_v2_1.sh.
# =============================================================================
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

OUT=results/smoke
RUN_NAME="smoke_v2_$(date +%Y%m%d_%H%M%S)"
STUB=0
for arg in "$@"; do [[ "$arg" == "-stub-run" ]] && STUB=1; done

# Huella del contrato vigente antes de correr
CONTRACT=results/data/run_manifest.json
before=""
[[ -f "$CONTRACT" ]] && before=$(sha256sum "$CONTRACT" | cut -d' ' -f1)

mkdir -p "$OUT/pipeline_info"
echo "▶ Humo V2.0 (main_v2.nf) — run: ${RUN_NAME} · outdir: ${OUT}"

nextflow run main_v2.nf \
    -profile docker,romero-v2,smoke \
    -name "${RUN_NAME}" \
    "$@"

echo "▶ Verificando aislamiento del contrato vigente..."
after=""
[[ -f "$CONTRACT" ]] && after=$(sha256sum "$CONTRACT" | cut -d' ' -f1)
if [[ "$before" != "$after" ]]; then
    echo "✗ results/data/run_manifest.json cambió: la prueba de humo contaminó producción." >&2
    exit 1
fi
echo "  ✓ results/data intacto"

if [[ "$STUB" -eq 1 ]]; then
    echo "✓ stub-run completado (revisa en el reporte el número de tareas RUN_VINA)."
    exit 0
fi

echo "▶ Verificando contrato de V2.0..."
python3 - "$OUT/data" <<'PY'
import json, sys
from pathlib import Path

data = Path(sys.argv[1])
variants = json.loads((data / "top_variants.json").read_text(encoding="utf-8"))
metrics = json.loads((data / "structural_metrics.json").read_text(encoding="utf-8"))
manifest = json.loads((data / "manifest_structures.json").read_text(encoding="utf-8"))

for row in variants:
    key = f"{row['hugo_symbol']}_{row['protein_change']}"
    assert key in metrics, f"{key}: sin entrada en structural_metrics.json"
    assert isinstance(metrics[key].get("rmsd_global"), (int, float)), \
        f"{key}: sin rmsd_global (ALIGN_WT_MUT no corrió)"
    assert "wt_structure" not in metrics[key], \
        f"{key}: V2.0 no debe escribir wt_structure (es de V2.1)"

genes = {row["hugo_symbol"] for row in variants}
for gene in genes:
    assert f"{gene}_WT" in manifest, f"{gene}: falta el WT único por gen (<GEN>_WT)"
    per_variant = [k for k in manifest if k.startswith(f"{gene}_WT_")]
    assert not per_variant, f"{gene}: V2.0 no debe generar WT por variante: {per_variant}"

assert not (data / "docking" / "vina_roles.json").exists(), \
    "V2.0 no debe generar docking/vina_roles.json (es de V2.1)"

print(f"  ✓ {len(variants)} variantes con RMSD, WT único por gen: {', '.join(sorted(genes))}")
PY

echo "✓ Humo V2.0 OK. Salida en ${OUT}/"
