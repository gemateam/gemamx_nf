#!/usr/bin/env bash
# Prueba determinista de docking (sin red, salvo la imagen ya construida).
#
#   RECEPTOR=/ruta/al/receptor.pdb bash tests/run_phase2_docking.sh
#
# Opcional, para centrar la caja en un residuo:
#   MUTATION_POS=1047 MODEL_START=867 EXPECTED_AA=H ...
#
# Comprueba:
#   - PREP_LIGAND y PREP_RECEPTOR dan bytes idénticos en ejecuciones separadas;
#   - RUN_VINA da la misma afinidad y las mismas poses con la misma semilla;
#   - MERGE_POSE produce un PDB con receptor y ligando.
set -euo pipefail

if [[ -z "${RECEPTOR:-}" ]]; then
  echo "ERROR: define RECEPTOR=/ruta/receptor.pdb" >&2
  exit 2
fi
if [[ ! -f "$RECEPTOR" ]]; then
  echo "ERROR: no existe RECEPTOR=$RECEPTOR" >&2
  exit 2
fi

PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BIN="$PROJECT_DIR/bin"
CATALOG="$PROJECT_DIR/assets/drug_catalog.csv"
W=${WORK:-/tmp/gemamx-nf-phase2-docking}
IMG=${IMG:-gemamx-cpu:1.0.0}
DOCK_IMG=${DOCK_IMG:-gemamx-nf-docking:1.0.0}
SEED=${SEED:-42}
DRUG=${DRUG:-Alpelisib}

rm -rf "$W" 2>/dev/null || true
mkdir -p "$W/struct" "$W/a" "$W/b"
cp "$RECEPTOR" "$W/struct/receptor.pdb"

run () {
  local image=$1 work=$2; shift 2
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$BIN":/bin:ro -v "$CATALOG":/assets/drug_catalog.csv:ro \
    -v "$W":/work -w "/work/$work" \
    --entrypoint python "$image" "/bin/$@"
}

echo '=== PREP_LIGAND (2x) ==='
for tag in a b; do
  run "$DOCK_IMG" "$tag" prep_ligand.py \
    --catalog /assets/drug_catalog.csv --drug "$DRUG" --seed "$SEED" \
    --out ligand.pdbqt --meta ligand.json
done
cmp -s "$W/a/ligand.pdbqt" "$W/b/ligand.pdbqt"
echo "ligando determinista: $(sha256sum "$W/a/ligand.pdbqt" | cut -d' ' -f1)"

echo '=== PREP_RECEPTOR (2x) ==='
for tag in a b; do
  run "$IMG" "$tag" prep_receptor.py \
    --structure /work/struct/receptor.pdb --seed "$SEED" \
    --out receptor.pdbqt --meta receptor.json
done
cmp -s "$W/a/receptor.pdbqt" "$W/b/receptor.pdbqt"
echo "receptor determinista: $(sha256sum "$W/a/receptor.pdbqt" | cut -d' ' -f1)"

echo '=== DOCK_CENTER ==='
if [[ -n "${MUTATION_POS:-}" ]]; then
  run "$IMG" a dock_center.py \
    --receptor receptor.pdbqt --out box.json --mode mutation \
    --mutation-pos "$MUTATION_POS" --model-start "${MODEL_START:-1}" \
    --expected-aa "${EXPECTED_AA:-}" --box-size "${BOX_SIZE:-25}"
else
  run "$IMG" a dock_center.py \
    --receptor receptor.pdbqt --out box.json --mode centroid \
    --box-size "${BOX_SIZE:-25}"
fi

python3 - "$W/a/box.json" <<'PY'
import json, sys
box = json.load(open(sys.argv[1]))
print('caja:', box['center_x'], box['center_y'], box['center_z'], '| tamaño', box['box_size'])
assert box['box_size'] > 0
PY

read -r CX CY CZ < <(python3 - "$W/a/box.json" <<'PY'
import json, sys
box = json.load(open(sys.argv[1]))
print(box['center_x'], box['center_y'], box['center_z'])
PY
)

echo '=== RUN_VINA (2x) ==='
for tag in a b; do
  run "$IMG" "$tag" run_vina.py \
    --receptor receptor.pdbqt --ligand ligand.pdbqt \
    --center "$CX" "$CY" "$CZ" --box-size "${BOX_SIZE:-25}" \
    --seed "$SEED" --exhaustiveness "${EXHAUSTIVENESS:-1}" --num-modes 3 \
    --timeout 600 --variant TEST --drug "$DRUG" \
    --out pose.pdbqt --log vina.log --summary summary.json
done

python3 - "$W" <<'PY'
import json, sys
root = sys.argv[1]
a = json.load(open(f'{root}/a/summary.json'))
b = json.load(open(f'{root}/b/summary.json'))
print('afinidad:', a['best_affinity'], '| poses:',
      [(m['mode'], m['affinity']) for m in a['modes']])
assert a['best_affinity'] == b['best_affinity'], (a, b)
assert a['modes'] == b['modes'], 'las poses no son deterministas'
PY
cmp -s "$W/a/pose.pdbqt" "$W/b/pose.pdbqt"

echo '=== MERGE_POSE ==='
run "$IMG" a merge_pose.py \
  --receptor-pdbqt receptor.pdbqt --ligand-out-pdbqt pose.pdbqt \
  --out complex.pdb

python3 - "$W/a/complex.pdb" <<'PY'
import sys
atoms = sum(1 for line in open(sys.argv[1]) if line.startswith('ATOM'))
het = sum(1 for line in open(sys.argv[1]) if line.startswith('HETATM'))
print('complejo:', atoms, 'átomos de proteína,', het, 'átomos de ligando')
assert atoms > 0 and het > 0
PY

echo 'OK phase2-docking'
