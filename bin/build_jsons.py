#!/usr/bin/env python3
"""BUILD_JSONS — ensambla los contratos de datos desde los archivos de la corrida.

Entradas (todas producidas por procesos anteriores):
  --top / --raw / --stats      JSON de INGEST y BUILD_STATS
  --structure-meta (repetible) sidecars de PREDICT_STRUCTURE
  --rmsd (repetible)           resultados de ALIGN_WT_MUT
  --vina (repetible)           resúmenes de RUN_VINA
  --complex (repetible)        PDB de complejo de MERGE_POSE

Salidas (contrato que consume la app):
  structural_metrics.json, manifest_structures.json,
  vina_affinities.json (en docking/), top_variants.json, raw_mutations.json,
  mutation_stats.json,
  structures/*.pdb,
  docking/results/*_out.pdbqt,
  docking/complex/*_complex.pdb.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import die, read_json, write_json  # noqa: E402


def load_catalog_order(path: str | None) -> list[str]:
    if not path:
        return []
    with open(path, encoding="utf-8", newline="") as handle:
        return [row["name"].strip() for row in csv.DictReader(handle) if row.get("name")]


def main() -> int:
    parser = argparse.ArgumentParser(description="Ensambla los JSON de contrato")
    parser.add_argument("--top", required=True)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--stats", required=True)
    parser.add_argument("--structure-meta", action="append", default=[])
    parser.add_argument("--rmsd", action="append", default=[])
    parser.add_argument("--vina", action="append", default=[])
    parser.add_argument("--complex", action="append", default=[])
    parser.add_argument("--catalog")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--prefix", default="data/structures")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    top = read_json(args.top)
    if not isinstance(top, list):
        die(f"top_variants inválido: {args.top}")

    # --- estructuras: pLDDT, manifest, copia al contrato y mutation_resseq_model --
    structures_out = outdir / "structures"
    manifest: dict[str, str | None] = {}
    plddt: dict[str, float] = {}
    mut_resseq: dict[str, int] = {}   # variante → mutation_resseq_model
    for meta_path in args.structure_meta:
        meta = read_json(meta_path)
        gene = meta.get("gene")
        change = meta.get("protein_change", "WT")
        if not gene:
            die(f"meta sin gene: {meta_path}")
        key = f"{gene}_WT" if meta.get("role") == "wt" else f"{gene}_{change}"
        structure_file = meta.get("structure_file")
        if not structure_file:
            die(f"meta sin structure_file: {meta_path}")
        structure_path = Path(meta_path).with_name(structure_file)
        if not structure_path.is_file():
            die(f"no existe la estructura {structure_path} referida por {meta_path}")
        structures_out.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(structure_path, structures_out / structure_file)
        # Si el sidecar indica un .cif hermano, copiarlo también y usar ese en el manifest
        cif_name = meta.get("structure_cif")
        if cif_name:
            cif_path = Path(meta_path).with_name(cif_name)
            if cif_path.is_file():
                shutil.copyfile(cif_path, structures_out / cif_name)
                manifest[key] = f"{args.prefix.rstrip('/')}/{cif_name}"
            else:
                manifest[key] = f"{args.prefix.rstrip('/')}/{structure_file}"
        else:
            manifest[key] = f"{args.prefix.rstrip('/')}/{structure_file}"
        if "plddt_mean" in meta:
            plddt[key] = float(meta["plddt_mean"])
        # Guardar posición del residuo mutado en el modelo (para highlight en webapp)
        if "mutation_resseq_model" in meta:
            mut_resseq[key] = int(meta["mutation_resseq_model"])

    # --- RMSD por variante ------------------------------------------------
    rmsd_by_variant: dict[str, dict] = {}
    for rmsd_path in args.rmsd:
        rmsd = read_json(rmsd_path)
        gene = rmsd.get("gene")
        change = rmsd.get("protein_change")
        if not gene or not change:
            die(f"RMSD sin gene/protein_change: {rmsd_path}")
        rmsd_by_variant[f"{gene}_{change}"] = rmsd

    # --- afinidades Vina ---------------------------------------------------
    order = load_catalog_order(args.catalog)
    order_index = {name: i for i, name in enumerate(order)}
    vina_by_variant: dict[str, dict[str, float]] = {}
    poses_out = outdir / "docking" / "results"
    for summary_path in args.vina:
        summary = read_json(summary_path)
        variant = summary.get("variant")
        drug = summary.get("drug")
        score = summary.get("best_affinity")
        if not variant or not drug or score is None:
            die(f"resumen de Vina incompleto: {summary_path}")
        vina_by_variant.setdefault(variant, {})[drug] = round(float(score), 3)
        pose_name = summary.get("out_pdbqt")
        if pose_name:
            pose_path = Path(summary_path).with_name(pose_name)
            if not pose_path.is_file():
                die(f"no existe la pose {pose_path} referida por {summary_path}")
            poses_out.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(pose_path, poses_out / pose_name)

    # --- complejos receptor + pose 1 --------------------------------------
    complexes_out = outdir / "docking" / "complex"
    for complex_path in args.complex:
        source = Path(complex_path)
        if not source.is_file():
            die(f"no existe el complejo: {source}")
        complexes_out.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, complexes_out / source.name)

    # --- contratos ---------------------------------------------------------
    metrics: dict[str, dict] = {}

    # Afinidades de todas las corridas de Vina, incluidas las del WT (que se
    # dockea una vez por gen para comparar). El WT no genera entrada en
    # structural_metrics.json: sólo las variantes con RMSD lo hacen.
    affinities: dict[str, dict[str, float]] = {}
    for variant, scores in sorted(vina_by_variant.items()):
        affinities[variant] = dict(sorted(
            scores.items(),
            key=lambda kv: (order_index.get(kv[0], len(order_index)), kv[0]),
        ))

    for variant, rmsd in sorted(rmsd_by_variant.items()):
        gene = rmsd["gene"]
        scores = affinities.get(variant, {})
        entry = {
            "wt_plddt": plddt.get(f"{gene}_WT"),
            "mut_plddt": plddt.get(variant),
            "rmsd_global": rmsd["rmsd_global"],
            "rmsd_active": rmsd["rmsd_active"],
            "rmsd_regions": rmsd.get("rmsd_regions", []),
        }
        if variant in mut_resseq:
            entry["mutation_resseq_model"] = mut_resseq[variant]
        if scores:
            best_drug = min(scores, key=lambda d: (scores[d], d))
            entry["best_vina_drug"] = best_drug
            entry["best_vina_score"] = scores[best_drug]
            entry["vina_scores"] = scores
        metrics[variant] = entry

    # Variantes priorizadas sin estructura -> null explícito en el manifest
    for row in top:
        key = f"{row['hugo_symbol']}_{row['protein_change']}"
        manifest.setdefault(key, None)
        manifest.setdefault(f"{row['hugo_symbol']}_WT", None)

    write_json(outdir / "structural_metrics.json", metrics, sort_keys=True)
    write_json(outdir / "docking" / "vina_affinities.json", affinities, sort_keys=True)
    write_json(outdir / "manifest_structures.json", manifest, sort_keys=True)

    # Copias byte a byte de los JSON de ingesta/estadística
    for source, name in ((args.top, "top_variants.json"),
                         (args.raw, "raw_mutations.json"),
                         (args.stats, "mutation_stats.json")):
        shutil.copyfile(source, outdir / name)

    print(f"OK contratos: {len(metrics)} variantes, {len(affinities)} con docking, "
          f"{len(manifest)} entradas de manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
