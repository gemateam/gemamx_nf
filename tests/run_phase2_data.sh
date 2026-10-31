#!/usr/bin/env bash
# Prueba de los scripts de ingesta, FASTA y estructuras (requiere red).
#
#   bash tests/run_phase2_data.sh
#
# Usa la API de UniProt y la de ESMFold. Si ESMFold no responde, la prueba
# falla en el paso PREDICT_STRUCTURE (no hay resultados parciales).
set -euo pipefail

PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BIN="$PROJECT_DIR/bin"
REF="$PROJECT_DIR/tests/reference"
W=${WORK:-/tmp/gemamx-nf-phase2-data}
IMG=${IMG:-gemamx-cpu:1.0.0}

rm -rf "$W" 2>/dev/null || true
mkdir -p "$W"

run () {
  docker run --rm \
    --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$BIN":/bin:ro -v "$REF":/ref:ro -v "$W":/work -w /work \
    --entrypoint python "$IMG" "/bin/$@"
}

echo '=== INGEST (snapshot) ==='
run ingest_cbioportal.py \
  --outdir /work/ingest \
  --genes PIK3CA,TP53,AKT1 \
  --max-variants 3 \
  --mutations-json /ref/mutations_snapshot.json

python3 - "$W" <<'PY'
import json, sys
top = json.load(open(f'{sys.argv[1]}/ingest/top_variants.json'))
for row in top:
    print(row['rank'], row['hugo_symbol'], row['protein_change'],
          row['frequency'], row['classification'])
PY

echo '=== BUILD_STATS ==='
run build_stats.py --raw /work/ingest/raw_mutations.json \
  --out /work/ingest/mutation_stats.json
cat "$W/ingest/mutation_stats.json"

echo '=== FETCH_FASTA PIK3CA H1047R (UniProt) ==='
run fetch_fasta.py --gene PIK3CA --protein-change H1047R --outdir /work/fasta

python3 - "$W" <<'PY'
import json, re, sys
root = sys.argv[1]
for name in ('PIK3CA_WT', 'PIK3CA_H1047R'):
    meta = json.load(open(f'{root}/fasta/{name}.json'))
    seq = ''.join(l.strip() for l in open(f'{root}/fasta/{name}.fasta')
                  if not l.startswith('>'))
    print(name, len(seq), 'aa', '| pos 1047 =', seq[1046])
    assert re.match(r'^[ACDEFGHIKLMNPQRSTVWY]+$', seq), 'secuencia no proteica'
    assert meta['mutation_pos'] == 1047
PY

echo '=== PREDICT_STRUCTURE WT (ESMFold, ventana) ==='
run predict_structure.py \
  --fasta /work/fasta/PIK3CA_WT.fasta --gene PIK3CA --protein-change H1047R \
  --role wt --out /work/struct/PIK3CA_WT.pdb --meta /work/struct/PIK3CA_WT.json \
  --window 180 --timeout 300

echo '=== PREDICT_STRUCTURE MUT (ESMFold, misma ventana) ==='
run predict_structure.py \
  --fasta /work/fasta/PIK3CA_H1047R.fasta --gene PIK3CA --protein-change H1047R \
  --role mut --out /work/struct/PIK3CA_H1047R.pdb \
  --meta /work/struct/PIK3CA_H1047R.json \
  --window 180 --timeout 300

python3 - "$W" <<'PY'
import json, sys
root = sys.argv[1]
for name in ('PIK3CA_WT', 'PIK3CA_H1047R'):
    m = json.load(open(f'{root}/struct/{name}.json'))
    print(name, 'modelo', m['model_start'], '..', m['model_end'],
          '| pLDDT', m['plddt_mean'], '| resseq mut', m.get('mutation_resseq_model'))
    assert m['mutation_resseq_model'] == 181, m
    assert 0 < m['plddt_mean'] <= 100
PY

echo '=== ALIGN_WT_MUT ==='
run align_wt_mut.py \
  --wt /work/struct/PIK3CA_WT.pdb --mut /work/struct/PIK3CA_H1047R.pdb \
  --wt-meta /work/struct/PIK3CA_WT.json --mut-meta /work/struct/PIK3CA_H1047R.json \
  --out /work/struct/PIK3CA_H1047R_rmsd.json
cat "$W/struct/PIK3CA_H1047R_rmsd.json"

echo '=== BUILD_MANIFEST ==='
run build_manifest.py --structures-dir /work/struct --out /work/struct/manifest.json
cat "$W/struct/manifest.json"

echo 'OK phase2-data'
