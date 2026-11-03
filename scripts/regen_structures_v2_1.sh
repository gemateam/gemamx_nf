#!/usr/bin/env bash
# =============================================================================
# Regenera las 6 estructuras de V2.1 (WT y MUT de PIK3CA_H1047R, PIK3CA_E542K y
# AKT1_E17K) con el centro y la ventana de docs/V2_1.md §2, para que el
# fragmento contenga el bolsillo ATP (assets/binding_sites.csv).
#
#   bash scripts/regen_structures_v2_1.sh            # pliega en staging y valida
#   bash scripts/regen_structures_v2_1.sh --promote  # además respalda y promueve
#
# Staging: results/_regen_v2_1/   (no toca los fixtures hasta usar --promote)
# Destino: tests/reference/romero_v2/structures/
#          WT__<GEN>_<CAMBIO>.pdb  y  <GEN>_<CAMBIO>.pdb
#
# Variables opcionales:
#   OUTER_RETRIES   reintentos por estructura si la API de ESMFold da 504 (5)
#   IMAGE           imagen con Biopython+requests si el host no las tiene
#   EXPECT_UNCOVERED variantes que se aceptan sin cubrir el bolsillo
#                    (por defecto PIK3CA_E542K: 542 y 802-933 no caben en 388 aa)
#
# Notas:
#   - E542K usa centro 542 (la mutación): es el comportamiento V2 y reproduce el
#     fragmento 362-721 que ya existe; el bolsillo no cabe en el mismo fragmento.
#   - predict_structure.py valida que el residuo WT/MUT coincida con la mutación;
#     si no coincide, aborta (y este script reintenta antes de rendirse).
# =============================================================================
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

FASTA=tests/reference/romero_v2/fasta
DEST=tests/reference/romero_v2/structures
STAGE=results/_regen_v2_1
SITES=assets/binding_sites.csv
SITE_NAME=ATP_pocket
OUTER_RETRIES=${OUTER_RETRIES:-5}
EXPECT_UNCOVERED=${EXPECT_UNCOVERED:-PIK3CA_E542K}
PROMOTE=0
[[ "${1:-}" == "--promote" ]] && PROMOTE=1

# gen  cambio  centro  ventana   (tabla de docs/V2_1.md §2)
VARIANTS=(
    "PIK3CA H1047R 924 180"
    "PIK3CA E542K  542 180"
    "AKT1   E17K   154 180"
)

if python3 -c "import Bio, requests" 2>/dev/null; then
    run_py() { python3 "$@"; }
else
    IMAGE=${IMAGE:-gemamx-cpu:1.0.0}
    echo "ℹ Biopython/requests no están en el host; uso Docker (${IMAGE})"
    run_py() { docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":/work -w /work "$IMAGE" python3 "$@"; }
fi

fold() {
    local n=1
    until run_py bin/predict_structure.py "$@"; do
        if (( n >= OUTER_RETRIES )); then
            echo "✗ falló tras ${n} intentos: $*" >&2
            return 1
        fi
        echo "  ⟳ reintento ${n}/${OUTER_RETRIES} en $((20 * n))s (ESMFold intermitente)"
        sleep $((20 * n))
        n=$((n + 1))
    done
}

mkdir -p "$STAGE"
rm -f "$STAGE"/*.pdb "$STAGE"/*.json

for v in "${VARIANTS[@]}"; do
    read -r gene change center window <<<"$v"
    echo "▶ ${gene}_${change}: centro ${center}, ventana ±${window}"

    fold --fasta "$FASTA/${gene}_WT.fasta" \
         --gene "$gene" --protein-change WT --wt-for "$change" --role wt \
         --backend esmfold --window-center "$center" --window "$window" \
         --out  "$STAGE/WT__${gene}_${change}.pdb" \
         --meta "$STAGE/WT__${gene}_${change}.json"

    fold --fasta "$FASTA/${gene}_${change}.fasta" \
         --gene "$gene" --protein-change "$change" --role mut \
         --backend esmfold --window-center "$center" --window "$window" \
         --out  "$STAGE/${gene}_${change}.pdb" \
         --meta "$STAGE/${gene}_${change}.json"
done

echo "▶ Validando ventanas, mutación y cobertura del bolsillo..."
python3 - "$STAGE" "$SITES" "$SITE_NAME" "$EXPECT_UNCOVERED" <<'PY'
import csv, json, sys
from pathlib import Path

stage, sites_csv, site_name, expect = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
expect_uncovered = {x for x in expect.replace(",", " ").split() if x}

sites = {}
with open(sites_csv, encoding="utf-8", newline="") as fh:
    for row in csv.DictReader(fh):
        if row["site_name"] == site_name:
            sites[row["gene"]] = [int(x) for x in row["residues"].split(";") if x.strip()]

variants = [("PIK3CA", "H1047R"), ("PIK3CA", "E542K"), ("AKT1", "E17K")]
errors, rows = [], []
for gene, change in variants:
    vid = f"{gene}_{change}"
    wt = json.loads((stage / f"WT__{vid}.json").read_text(encoding="utf-8"))
    mut = json.loads((stage / f"{vid}.json").read_text(encoding="utf-8"))
    lo, hi = mut["model_start"], mut["model_end"]
    if (wt["model_start"], wt["model_end"]) != (lo, hi):
        errors.append(f"{vid}: WT ({wt['model_start']}-{wt['model_end']}) y MUT ({lo}-{hi}) no cubren la misma región")
    if not (wt.get("mutation_in_model") and mut.get("mutation_in_model")):
        errors.append(f"{vid}: la mutación no está dentro del modelo")
    pocket = sites.get(gene, [])
    missing = [r for r in pocket if not lo <= r <= hi]
    covered = bool(pocket) and not missing
    if not covered and vid not in expect_uncovered:
        errors.append(f"{vid}: el bolsillo no queda cubierto (faltan {missing}); esperado en {sorted(expect_uncovered)}")
    rows.append((vid, f"{lo}-{hi}", mut["model_length"], mut["plddt_mean"], wt["plddt_mean"],
                 "sí" if covered else f"NO (faltan {missing})"))

print(f"  {'variante':<15}{'modelo':<11}{'aa':<5}{'pLDDT MUT':<11}{'pLDDT WT':<10}bolsillo")
for r in rows:
    print(f"  {r[0]:<15}{r[1]:<11}{r[2]:<5}{r[3]:<11}{r[4]:<10}{r[5]}")
if errors:
    print("\n✗ Validación fallida:", file=sys.stderr)
    for e in errors:
        print(f"  - {e}", file=sys.stderr)
    sys.exit(1)
print("  ✓ validación OK")
PY

if [[ "$PROMOTE" -ne 1 ]]; then
    echo "✓ Estructuras en ${STAGE}/ (fixtures sin cambios). Revisa y repite con --promote."
    exit 0
fi

BACKUP="tests/reference/romero_v2/structures_backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP"
for v in "${VARIANTS[@]}"; do
    read -r gene change _ _ <<<"$v"
    for f in "WT__${gene}_${change}.pdb" "${gene}_${change}.pdb"; do
        [[ -f "$DEST/$f" ]] && cp -p "$DEST/$f" "$BACKUP/$f"
        cp -f "$STAGE/$f" "$DEST/$f"
    done
done
echo "✓ Promovidas 6 estructuras a ${DEST}/ (respaldo en ${BACKUP}/)"
echo "  Siguiente: bash tests/run_smoke_v2_1.sh  y revisa site_covered en vina_roles.json"
