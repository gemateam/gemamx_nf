#!/usr/bin/env python3
"""ALIGN_WT_MUT — RMSD real entre WT y MUT (CA emparejados por resSeq).

No existía en el legado. Método:
  1. Se emparejan residuos por número (resSeq) presentes en ambos modelos.
  2. Superposición global con SVD (Biopython SVDSuperimposer) -> rmsd_global.
  3. rmsd_active: RMSD de los CA dentro de --active-radius Å del residuo mutado
     (en coordenadas WT, tras la superposición global).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from Bio.SVDSuperimposer import SVDSuperimposer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import die, parse_mutation, read_json, write_json  # noqa: E402
from predict_structure import load_ca  # noqa: E402


def index_by_resseq(residues: list[dict]) -> dict[int, dict]:
    indexed: dict[int, dict] = {}
    for residue in residues:
        indexed.setdefault(residue["resseq"], residue)
    return indexed


def color_for(value: float) -> str:
    if value < 1.5:
        return "#10b981"
    if value < 3.0:
        return "#f59e0b"
    return "#f87171"


def main() -> int:
    parser = argparse.ArgumentParser(description="Calcula RMSD WT vs MUT")
    parser.add_argument("--wt", required=True)
    parser.add_argument("--mut", required=True)
    parser.add_argument("--wt-meta", required=True)
    parser.add_argument("--mut-meta", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--active-radius", type=float, default=10.0)
    parser.add_argument("--min-matched", type=int, default=30)
    args = parser.parse_args()

    wt_meta = read_json(args.wt_meta)
    mut_meta = read_json(args.mut_meta)

    change = mut_meta.get("protein_change", "WT")
    if change == "WT":
        die("el meta MUT no tiene protein_change")
    wt_aa, mutation_pos, mut_aa = parse_mutation(change)

    if wt_meta.get("gene") != mut_meta.get("gene"):
        die(f"genes distintos: {wt_meta.get('gene')} vs {mut_meta.get('gene')}")

    wt_res = index_by_resseq(load_ca(Path(args.wt)))
    mut_res = index_by_resseq(load_ca(Path(args.mut)))
    common = sorted(set(wt_res) & set(mut_res))
    if len(common) < args.min_matched:
        die(f"solo {len(common)} residuos CA en común (mínimo {args.min_matched}). "
            f"¿WT y MUT se predijeron con ventanas distintas?")

    wt_coords = np.array([wt_res[r]["coord"] for r in common], dtype=float)
    mut_coords = np.array([mut_res[r]["coord"] for r in common], dtype=float)

    superimposer = SVDSuperimposer()
    superimposer.set(wt_coords, mut_coords)
    superimposer.run()
    rmsd_global = float(superimposer.get_rms())
    rotation, translation = superimposer.get_rotran()
    mut_aligned = (mut_coords @ rotation) + translation

    mut_resseq = int(mut_meta["mutation_resseq_model"])
    wt_resseq = int(wt_meta["mutation_resseq_model"])

    for label, indexed, resseq, expected in (
        ("WT", wt_res, wt_resseq, wt_aa),
        ("MUT", mut_res, mut_resseq, mut_aa),
    ):
        residue = indexed.get(resseq)
        if residue is None:
            die(f"{label}: el residuo {mutation_pos} (modelo: {resseq}) no está en la estructura")
        if residue["one"] != expected:
            die(f"{label}: residuo {mutation_pos} es {residue['resname']} "
                f"({residue['one']}), se esperaba {expected}")

    # Sitio activo: residuos del WT cerca del residuo mutado (coordenadas WT)
    mutation_coord = np.array(wt_res[wt_resseq]["coord"], dtype=float)
    distances = np.linalg.norm(wt_coords - mutation_coord, axis=1)
    active_mask = distances <= args.active_radius
    if active_mask.sum() < 5:
        die(f"muy pocos residuos en el sitio activo ({int(active_mask.sum())})")
    active_rmsd = float(np.sqrt(np.mean(
        np.sum((wt_coords[active_mask] - mut_aligned[active_mask]) ** 2, axis=1)
    )))

    wt_resname = wt_res[wt_resseq]["resname"].title()
    mut_resname = mut_res[mut_resseq]["resname"].title()
    if wt_resname == mut_resname:
        die(f"el residuo {mutation_pos} es {wt_resname} en WT y MUT: la mutación no está aplicada")

    result = {
        "gene": mut_meta["gene"],
        "protein_change": change,
        "rmsd_global": round(rmsd_global, 3),
        "rmsd_active": round(active_rmsd, 3),
        "rmsd_regions": [{
            "region": f"Sitio activo {change}",
            "value": round(active_rmsd, 3),
            "color": color_for(active_rmsd),
        }],
        "matched_residues": len(common),
        "active_residues": int(active_mask.sum()),
        "active_radius": args.active_radius,
        "mutation_pos": mutation_pos,
        "mutation_resseq_model": mut_resseq,
        "wt_residue": wt_resname.upper(),
        "mut_residue": mut_resname.upper(),
        "wt_file": Path(args.wt).name,
        "mut_file": Path(args.mut).name,
    }
    write_json(args.out, result, sort_keys=True)
    print(f"OK RMSD {change}: global {result['rmsd_global']} Å, "
          f"activo {result['rmsd_active']} Å ({len(common)} CA emparejados)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
