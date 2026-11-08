#!/usr/bin/env python3
"""BUILD_STATS — mutation_stats.json desde raw_mutations.json.

Mismo contrato que el legado: distribución de genes (top 20), distribución de
tipos de variante, total de muestras y total de mutaciones. Determinista.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import die, read_json, write_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera mutation_stats.json")
    parser.add_argument("--raw", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--total-samples", type=int,
                        help="tamaño de cohorte (por defecto, muestras únicas)")
    parser.add_argument("--contract-dir",
                        help="bundle del contrato; su manifiesto define el tamaño de cohorte")
    parser.add_argument("--top-genes", type=int, default=20)
    args = parser.parse_args()

    rows = read_json(args.raw)
    if not isinstance(rows, list) or not rows:
        die(f"raw_mutations vacío o inválido: {args.raw}")

    gene_counts = Counter(r.get("hugo_symbol") for r in rows if r.get("hugo_symbol"))
    type_counts = Counter(r.get("variant_classification") for r in rows
                          if r.get("variant_classification"))

    gene_sorted = sorted(gene_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    type_sorted = sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0]))

    samples = {r.get("sample_id") for r in rows if r.get("sample_id")}
    patient_ids = {r.get("patient_id") for r in rows if r.get("patient_id")}
    if args.contract_dir:
        manifest_path = Path(args.contract_dir) / "manifest.json"
        manifest = read_json(manifest_path)
        cohort = manifest.get("cohort") or {}
        contract_counts = manifest.get("counts") or {}
        total_samples = cohort.get("total_cases") or contract_counts.get("cohort_cases")
        if not total_samples:
            die(f"el manifiesto no declara el tamaño de la cohorte: {manifest_path}")
        if args.total_samples and args.total_samples != total_samples:
            print(f"AVISO: --total-samples {args.total_samples} difiere del "
                  f"manifiesto ({total_samples}); se usa el manifiesto", file=sys.stderr)
        cohort_unit = "patient"
        mutation_carriers = contract_counts.get("mutation_patients")
        non_mutated_units = cohort.get("cases_without_mutations")
        if mutation_carriers is None:
            mutation_carriers = len(patient_ids)
        if non_mutated_units is None:
            non_mutated_units = max(0, total_samples - mutation_carriers)
    else:
        total_samples = args.total_samples if args.total_samples else len(samples)
        cohort_unit = "patient" if patient_ids else "sample"
        mutation_carriers = len(patient_ids) if patient_ids else len(samples)
        non_mutated_units = max(0, total_samples - mutation_carriers)
    if total_samples <= 0:
        die("no se pudo determinar el número de muestras")

    stats = {
        "gene_distribution": {gene: count for gene, count in gene_sorted[:args.top_genes]},
        "type_distribution": {variant_type: count for variant_type, count in type_sorted},
        "total_samples": total_samples,
        "cohort_unit": cohort_unit,
        "cohort_units_with_mutations": mutation_carriers,
        "cohort_units_without_mutations": non_mutated_units,
        "total_mutations": len(rows),
    }
    write_json(args.out, stats)
    print(f"OK stats: {len(gene_counts)} genes, {len(type_counts)} tipos, "
          f"{len(rows)} mutaciones, {total_samples} muestras")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
