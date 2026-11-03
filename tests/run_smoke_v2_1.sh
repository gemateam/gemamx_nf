#!/usr/bin/env bash
# =============================================================================
# Prueba de humo de main_v2_1.nf (un WT por variante, solo CPU).
#
#   bash tests/run_smoke_v2_1.sh            # corrida real, aislada
#   bash tests/run_smoke_v2_1.sh -stub-run  # solo valida canales (sin Docker)
#
# Aislamiento (perfil `smoke-v2-1`): outdir=results/smoke_v2_1,
# workDir=~/gemamx-work-smoke-v2-1, experimento MLflow GEMAMX-SMOKE-V2-1.
# Verifica que results/data (contrato vigente) no cambió.
#
# Comprueba:
#   - cada variante priorizada tiene RMSD (antes fallaba PIK3CA_E542K);
#   - cada variante tiene su WT en el manifest (<GEN>_WT_<CAMBIO>) y wt_structure;
#   - existe el alias canónico <GEN>_WT;
#   - solo se dockearon pares de assets/target_drug_map.csv.
# =============================================================================
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

OUT=results/smoke_v2_1
RUN_NAME="smoke_v2_1_$(date +%Y%m%d_%H%M%S)"
STUB=0
for arg in "$@"; do [[ "$arg" == "-stub-run" ]] && STUB=1; done

CONTRACT=results/data/run_manifest.json
before=""
[[ -f "$CONTRACT" ]] && before=$(sha256sum "$CONTRACT" | cut -d' ' -f1)

mkdir -p "$OUT/pipeline_info"
echo "▶ Humo main_v2_1 — run: ${RUN_NAME} · outdir: ${OUT}"

nextflow run main_v2_1.nf \
    -profile docker,romero-v2,v2_1,smoke-v2-1 \
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
    echo "✓ stub-run completado."
    exit 0
fi

echo "▶ Verificando WT por variante, RMSD y pares de docking..."
python3 - "$OUT/data" <<'PY'
import csv, json, sys
from pathlib import Path

data = Path(sys.argv[1])
top = json.loads((data / "top_variants.json").read_text(encoding="utf-8"))
metrics = json.loads((data / "structural_metrics.json").read_text(encoding="utf-8"))
manifest = json.loads((data / "manifest_structures.json").read_text(encoding="utf-8"))
aff = json.loads((data / "docking" / "vina_affinities.json").read_text(encoding="utf-8"))
roles = json.loads((data / "docking" / "vina_roles.json").read_text(encoding="utf-8"))

seen_genes = set()
for row in top:
    gene = row.get("hugo_symbol") or row.get("gene")
    pc = row["protein_change"]
    vid = f"{gene}_{pc}"
    assert vid in metrics, f"{vid}: sin RMSD en structural_metrics.json"
    wt_key = f"{gene}_WT_{pc}"
    assert manifest.get(wt_key), f"{vid}: falta {wt_key} en manifest_structures.json"
    assert metrics[vid].get("wt_structure") == wt_key, f"{vid}: wt_structure incorrecto"
    if gene not in seen_genes:
        seen_genes.add(gene)
        assert manifest.get(f"{gene}_WT") == manifest[wt_key], f"{gene}_WT no es alias de {wt_key}"

allowed = {}
with open("assets/target_drug_map.csv", encoding="utf-8", newline="") as fh:
    for row in csv.DictReader(fh):
        allowed.setdefault(row["gene"], {})[row["drug"]] = row["role"]

assert aff, "vina_affinities.json vacío"
for target, scores in aff.items():
    gene = target.split("_")[0]
    assert gene in allowed, f"{target}: gen sin pares en target_drug_map llegó a docking"
    for drug in scores:
        assert drug in allowed[gene], f"par no mapeado: {target} × {drug}"
        info = roles.get(target, {}).get(drug)
        assert info and info["role"] == allowed[gene][drug], f"rol inválido en {target} × {drug}"
        assert "site_covered" in info, f"sin site_covered registrado en {target} × {drug}"

uncovered = sorted({t for t, d in roles.items() for i in d.values() if i.get("site_covered") is False})

print(f"  ✓ {len(metrics)} variantes con RMSD y WT propio; "
      f"{len(aff)} dianas dockeadas, {sum(len(s) for s in aff.values())} pares")
if uncovered:
    print(f"  ⚠ site_covered=false (fragmento sin bolsillo, fallback centroid) en: "
          f"{', '.join(uncovered)}")
PY

echo "✓ Humo main_v2_1 OK. Salida en ${OUT}/"
