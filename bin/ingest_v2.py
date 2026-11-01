#!/usr/bin/env python3
"""INGEST_V2 — ensambla el contrato de datos del pipeline V2 (Romero-Córdoba).

A diferencia de BUILD_JSONS (que recibe sidecars de estructura y resúmenes
de Vina generados en caliente), este script toma los archivos pre-computados
del pipeline V2 ya ejecutado y los organiza en el árbol data/ que consume la
webapp y MLflow.

Entradas:
  --top             top_variants.json
  --raw             raw_mutations.json
  --stats           mutation_stats.json
  --structural      structural_metrics.json  (pre-computado por calc_structural_metrics_romero.py)
  --vina            vina_affinities.json     (pre-computado por run_docking_romero.py)
  --manifest        manifest_structures.json (pre-computado; rutas relativas a --struct-base)
  --clinical        variant_clinical_summary.json (pre-computado por build_variant_clinical_summary.py)
  --struct-dir      directorio con los PDB pre-computados (GENE_PC.pdb, GENE_WT.pdb)
  --catalog         drug_catalog.csv (orden de fármacos en la salida)
  --outdir          directorio de salida (stage/data)

Salidas (contrato de la webapp):
  top_variants.json, raw_mutations.json, mutation_stats.json
  structural_metrics.json, manifest_structures.json
  docking/vina_affinities.json
  variant_clinical_summary.json
  structures/*.pdb
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import die, read_json, write_json  # noqa: E402


def load_catalog_order(path: str | None) -> list[str]:
    if not path:
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return [row["name"].strip() for row in csv.DictReader(fh) if row.get("name")]


def main() -> int:
    parser = argparse.ArgumentParser(description="Ensambla contrato V2 desde archivos pre-computados")
    parser.add_argument("--top",        required=True, help="top_variants.json")
    parser.add_argument("--raw",        required=True, help="raw_mutations.json")
    parser.add_argument("--stats",      required=True, help="mutation_stats.json")
    parser.add_argument("--structural", required=True, help="structural_metrics.json pre-computado")
    parser.add_argument("--vina",       required=True, help="vina_affinities.json pre-computado")
    parser.add_argument("--manifest",   help="manifest_structures.json pre-computado (opcional; se reconstruye si no se indica)")
    parser.add_argument("--clinical",   help="variant_clinical_summary.json (opcional, M5)")
    parser.add_argument("--struct-dir", required=True, help="directorio con PDBs: GENE_PC.pdb, GENE_WT.pdb")
    parser.add_argument("--catalog",    help="drug_catalog.csv para ordenar fármacos")
    parser.add_argument("--outdir",     required=True, help="directorio de salida stage/data")
    parser.add_argument("--prefix",     default="data/structures", help="prefijo en manifest")
    args = parser.parse_args()

    outdir     = Path(args.outdir)
    struct_dir = Path(args.struct_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    # ── 1. Copias directas de JSON de ingesta ─────────────────────────────────
    for src_path, name in [
        (args.top,   "top_variants.json"),
        (args.raw,   "raw_mutations.json"),
        (args.stats, "mutation_stats.json"),
    ]:
        shutil.copyfile(src_path, outdir / name)

    # ── 2. Copiar clinical summary si existe ───────────────────────────────────
    if args.clinical and Path(args.clinical).is_file():
        shutil.copyfile(args.clinical, outdir / "variant_clinical_summary.json")

    # ── 3. structural_metrics.json — usar el pre-computado y asegurar campos ──
    structural_raw = read_json(args.structural)
    if not isinstance(structural_raw, dict):
        die(f"structural_metrics.json no es un dict: {args.structural}")

    # Normalizar: asegurar que best_vina_drug/score existan (ya los incluye el V2)
    # y que rmsd_regions esté presente (el V2 lo tiene).
    metrics: dict[str, dict] = {}
    for variant_id, entry in structural_raw.items():
        if not isinstance(entry, dict):
            continue
        metrics[variant_id] = entry

    write_json(outdir / "structural_metrics.json", metrics, sort_keys=True)

    # ── 4. vina_affinities.json — ordenar fármacos según catalog ──────────────
    order = load_catalog_order(args.catalog)
    order_index = {name: i for i, name in enumerate(order)}

    vina_raw = read_json(args.vina)
    if not isinstance(vina_raw, dict):
        die(f"vina_affinities.json no es un dict: {args.vina}")

    affinities: dict[str, dict] = {}
    for variant_id, scores in sorted(vina_raw.items()):
        if not isinstance(scores, dict):
            affinities[variant_id] = scores
            continue
        affinities[variant_id] = dict(sorted(
            scores.items(),
            key=lambda kv: (order_index.get(kv[0], len(order_index)), kv[0]),
        ))

    docking_dir = outdir / "docking"
    docking_dir.mkdir(parents=True, exist_ok=True)
    write_json(docking_dir / "vina_affinities.json", affinities, sort_keys=True)

    # ── 5. Copiar estructuras PDB y reconstruir manifest ──────────────────────
    structures_out = outdir / "structures"
    structures_out.mkdir(parents=True, exist_ok=True)

    # Reconstruir manifest con rutas al directorio de salida
    manifest_new: dict[str, str | None] = {}
    top = read_json(args.top)
    if not isinstance(top, list):
        die(f"top_variants.json no es lista: {args.top}")

    copied_pdbs = 0
    not_found = []

    # Copiar MUT PDBs
    for row in top:
        gene = row.get("hugo_symbol", "")
        pc   = row.get("protein_change", "")
        if not gene or not pc:
            continue
        mut_key = f"{gene}_{pc}"
        pdb_src = struct_dir / f"{mut_key}.pdb"
        if pdb_src.is_file():
            shutil.copyfile(pdb_src, structures_out / f"{mut_key}.pdb")
            manifest_new[mut_key] = f"{args.prefix.rstrip('/')}/{mut_key}.pdb"
            copied_pdbs += 1
        else:
            manifest_new[mut_key] = None
            not_found.append(f"{mut_key}.pdb")

        # WT del gen (un archivo por gen, no por variante)
        wt_key = f"{gene}_WT"
        if wt_key not in manifest_new:
            pdb_wt = struct_dir / f"{wt_key}.pdb"
            if pdb_wt.is_file():
                shutil.copyfile(pdb_wt, structures_out / f"{wt_key}.pdb")
                manifest_new[wt_key] = f"{args.prefix.rstrip('/')}/{wt_key}.pdb"
                copied_pdbs += 1
            else:
                manifest_new[wt_key] = None
                not_found.append(f"{wt_key}.pdb")

    write_json(outdir / "manifest_structures.json", manifest_new, sort_keys=True)

    if not_found:
        print(f"WARN: {len(not_found)} PDB(s) no encontrados: {', '.join(not_found[:5])}"
              + (f" (+{len(not_found)-5} más)" if len(not_found) > 5 else ""))

    n_variants  = len(metrics)
    n_docking   = sum(1 for v in affinities.values() if isinstance(v, dict) and v)
    print(f"OK contrato V2: {n_variants} variantes con métricas, "
          f"{n_docking} con docking, {copied_pdbs} PDBs copiados")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
