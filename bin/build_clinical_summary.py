#!/usr/bin/env python3
"""BUILD_CLINICAL_SUMMARY — M5b del pipeline V2.

Cruza las variantes priorizadas con los metadatos clínicos del cohorte
Romero-Córdoba 2021 para producir perfiles clínicos por variante:
edad, subtipo IHC, PAM50, grado SBR, histología.

Entradas:
  --raw       raw_mutations.json
  --clinical  clinical_metadata.json
  --top       top_variants.json
  --outdir    directorio de salida

Salida en --outdir:
  variant_clinical_summary.json

Derivado del script original v2/scripts/build_variant_clinical_summary.py;
refactorizado para aceptar rutas por argumento.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import die, read_json  # noqa: E402


def top_counts(counter: Counter, limit: int = 4) -> list[dict]:
    return [
        {"label": label, "count": count}
        for label, count in counter.most_common(limit)
        if label not in (None, "", "NA", "N/A")
    ]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Construye perfiles clínicos por variante (M5)")
    ap.add_argument("--raw",      required=True, help="raw_mutations.json")
    ap.add_argument("--clinical", required=True, help="clinical_metadata.json")
    ap.add_argument("--top",      required=True, help="top_variants.json")
    ap.add_argument("--outdir",   required=True, help="directorio de salida")
    args = ap.parse_args()

    raw_mutations = read_json(args.raw)
    clinical_rows = read_json(args.clinical)
    top_variants  = read_json(args.top)

    if not isinstance(raw_mutations, list):
        die(f"raw_mutations.json no es lista: {args.raw}")
    if not isinstance(clinical_rows, list):
        die(f"clinical_metadata.json no es lista: {args.clinical}")
    if not isinstance(top_variants, list):
        die(f"top_variants.json no es lista: {args.top}")

    clinical_by_sample = {
        row["sample_id"]: row for row in clinical_rows if row.get("sample_id")
    }

    target_variants = {
        row["hugo_symbol"] + "_" + row["protein_change"]
        for row in top_variants
        if row.get("hugo_symbol") and row.get("protein_change")
    }

    samples_by_variant: dict[str, set[str]] = defaultdict(set)
    for mut in raw_mutations:
        hugo = mut.get("hugo_symbol")
        pc   = mut.get("protein_change")
        sid  = mut.get("sample_id")
        if not (hugo and pc and sid):
            continue
        vid = hugo + "_" + pc
        if vid in target_variants:
            samples_by_variant[vid].add(sid)

    summaries: list[dict] = []
    for v in top_variants:
        vid = v["hugo_symbol"] + "_" + v["protein_change"]
        sample_ids   = sorted(samples_by_variant.get(vid, set()))
        matched_rows = [clinical_by_sample[s] for s in sample_ids
                        if s in clinical_by_sample]

        ages               = [r["age"] for r in matched_rows
                               if isinstance(r.get("age"), (int, float))]
        age_class_ctr      = Counter(r.get("age_class")  for r in matched_rows
                                      if r.get("age_class"))
        ihc_subtype_ctr    = Counter(r.get("ihc_subtype") for r in matched_rows
                                      if r.get("ihc_subtype"))
        class_ihc_ctr      = Counter(r.get("class_ihc")  for r in matched_rows
                                      if r.get("class_ihc"))
        pam50_ctr          = Counter(r.get("pam50")       for r in matched_rows
                                      if r.get("pam50"))
        grade_ctr          = Counter(r.get("grade_sbr")   for r in matched_rows
                                      if r.get("grade_sbr"))
        histology_ctr      = Counter(r.get("histology")   for r in matched_rows
                                      if r.get("histology"))

        summaries.append({
            "variant_id":              vid,
            "hugo_symbol":             v["hugo_symbol"],
            "protein_change":          v["protein_change"],
            "sample_count":            len(sample_ids),
            "matched_clinical_count":  len(matched_rows),
            "age": {
                "mean": round(mean(ages), 2) if ages else None,
                "min":  min(ages) if ages else None,
                "max":  max(ages) if ages else None,
            },
            "age_class_distribution":   dict(age_class_ctr),
            "ihc_subtype_distribution": dict(ihc_subtype_ctr),
            "class_ihc_distribution":   dict(class_ihc_ctr),
            "pam50_distribution":       dict(pam50_ctr),
            "grade_distribution":       dict(grade_ctr),
            "histology_distribution":   dict(histology_ctr),
            "highlights": {
                "top_age_class":    age_class_ctr.most_common(1)[0][0]   if age_class_ctr   else None,
                "top_ihc_subtype":  ihc_subtype_ctr.most_common(1)[0][0] if ihc_subtype_ctr else None,
                "top_class_ihc":    class_ihc_ctr.most_common(1)[0][0]   if class_ihc_ctr   else None,
                "top_pam50":        pam50_ctr.most_common(1)[0][0]       if pam50_ctr       else None,
            },
            "top_distributions": {
                "age_class":    top_counts(age_class_ctr,   limit=3),
                "ihc_subtype":  top_counts(ihc_subtype_ctr, limit=4),
                "class_ihc":    top_counts(class_ihc_ctr,   limit=4),
                "pam50":        top_counts(pam50_ctr,       limit=4),
                "grade":        top_counts(grade_ctr,       limit=4),
            },
        })

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "variant_clinical_summary.json").write_text(
        json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"OK resumen clínico V2: {len(summaries)} variantes con perfil clínico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
