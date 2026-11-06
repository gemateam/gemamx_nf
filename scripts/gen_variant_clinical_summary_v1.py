#!/usr/bin/env python3
"""
Genera variant_clinical_summary.json para runs V1 (TCGA-BRCA).

Cruza:
  - raw_mutations.json  → sample_id por variante  (TCGA-XXXX-01 → patientId TCGA-XXXX)
  - clinical_snapshot.json → RACE / ETHNICITY / AGE por patientId

Uso:
  python3 scripts/gen_variant_clinical_summary_v1.py \
      --mutations results/runs/<run>/data/raw_mutations.json \
      --clinical  tests/reference/clinical_snapshot.json \
      --out       results/runs/<run>/data/variant_clinical_summary.json
"""

import argparse, json, re, statistics
from pathlib import Path
from collections import defaultdict

SMALL_CELL_THRESHOLD = 5


def patient_id(sample_id: str) -> str:
    """TCGA-A1-B2C3-01 → TCGA-A1-B2C3  (elimina el sufijo de muestra)."""
    return re.sub(r'-\d{2}[A-Z]?$', '', sample_id)


def build_clinical_map(clinical_records):
    """
    Devuelve {patientId: {'RACE': ..., 'ETHNICITY': ..., 'AGE': ...}}
    """
    cmap = defaultdict(dict)
    for rec in clinical_records:
        pid = rec.get('patientId', '')
        attr = rec.get('clinicalAttributeId', '').upper()
        val  = rec.get('value', '').strip().upper()
        if attr in ('RACE', 'ETHNICITY', 'AGE') and pid and val not in ('', 'NA', 'NOT REPORTED', 'UNKNOWN'):
            cmap[pid][attr] = rec['value'].strip()   # guardar capitalización original
    return cmap


def count_dist(values):
    """Cuenta frecuencias, normaliza a str."""
    dist = defaultdict(int)
    for v in values:
        dist[str(v).strip()] += 1
    return dict(sorted(dist.items(), key=lambda x: -x[1]))


def small_cells(dist, dimension, threshold):
    return [f"{dimension}:{k}" for k, v in dist.items() if v < threshold]


def age_stats(ages):
    if not ages:
        return None
    return {
        'mean': round(statistics.mean(ages), 2),
        'min':  min(ages),
        'max':  max(ages),
    }


def process(mutations_path, clinical_path, out_path):
    mutations = json.loads(mutations_path.read_text(encoding='utf-8'))
    clinical  = json.loads(clinical_path.read_text(encoding='utf-8'))
    cmap      = build_clinical_map(clinical)

    # Agrupar sample_ids por variante
    variant_samples = defaultdict(set)
    for m in mutations:
        vid = f"{m['hugo_symbol']}_{m['protein_change']}"
        variant_samples[vid].add(m['sample_id'])

    results = []
    for vid, samples in sorted(variant_samples.items()):
        gene, pc = vid.split('_', 1)

        # Mapear sample → patient → datos clínicos
        matched = 0
        races, ethnicities, ages = [], [], []
        for sid in samples:
            pid = patient_id(sid)
            if pid in cmap:
                matched += 1
                rec = cmap[pid]
                if 'RACE' in rec:
                    races.append(rec['RACE'].upper())
                else:
                    races.append('SIN DATO')
                if 'ETHNICITY' in rec:
                    ethnicities.append(rec['ETHNICITY'].upper())
                else:
                    ethnicities.append('SIN DATO')
                if 'AGE' in rec:
                    try:
                        ages.append(int(rec['AGE']))
                    except ValueError:
                        pass

        race_dist = count_dist(races) if races else {}
        eth_dist  = count_dist(ethnicities) if ethnicities else {}

        sc = []
        sc += small_cells(race_dist,      'race',      SMALL_CELL_THRESHOLD)
        sc += small_cells(eth_dist, 'ethnicity', SMALL_CELL_THRESHOLD)

        entry = {
            'variant_id':            vid,
            'hugo_symbol':           gene,
            'protein_change':        pc,
            'sample_count':          len(samples),
            'matched_clinical_count': matched,
            'age':                   age_stats(ages),
            'ethnicity_distribution': eth_dist,
            'race_distribution':      race_dist,
            'small_cells':            sc,
            'small_cell_threshold':   SMALL_CELL_THRESHOLD,
            'clinical_data_note':    (
                f'* Indica celda con n < {SMALL_CELL_THRESHOLD} muestras (interpretación con cautela).'
                if any(c < SMALL_CELL_THRESHOLD for c in list(race_dist.values()) + list(eth_dist.values()))
                else None
            ),
            'clinical_source': 'TCGA-BRCA · cBioPortal (autorreportado)',
        }
        results.append(entry)
        print(f"  {vid}: {len(samples)} muestras, {matched} con clínica")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\nEscrito → {out_path}  ({len(results)} variantes)")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Genera variant_clinical_summary.json para runs V1 TCGA-BRCA')
    parser.add_argument('--mutations', required=True, type=Path)
    parser.add_argument('--clinical',  required=True, type=Path)
    parser.add_argument('--out',       required=True, type=Path)
    args = parser.parse_args()
    process(args.mutations, args.clinical, args.out)

