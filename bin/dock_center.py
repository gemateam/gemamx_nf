#!/usr/bin/env python3
"""DOCK_CENTER — centro de la caja de Vina.

Corrige el defecto del legado: el modelo puede estar renumerado desde 1
(fragmento de ESMFold), así que la posición proteica se traduce al resSeq del
modelo con

    pos_modelo = pos_proteína - (start - 1)

y el residuo se verifica (existe y, si se indica, coincide con el aminoácido
esperado). Si no se puede verificar, el proceso falla: no hay fallback
silencioso al centro de masa.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import AA3, AA3_TO_1, die, residue_range, write_json  # noqa: E402


def read_residue_atoms(pdbqt_path: Path, resseq: int) -> list[tuple[float, float, float, str, str]]:
    atoms = []
    with open(pdbqt_path, encoding="ascii", errors="ignore") as handle:
        for line in handle:
            if not line.startswith(("ATOM", "HETATM")):
                continue
            try:
                if int(line[22:26]) != resseq:
                    continue
                name = line[12:16].strip()
                resname = line[17:20].strip()
                ad4 = line[77:79].strip()
                x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
            except ValueError:
                continue
            if ad4 in ("HD", "H"):
                continue
            atoms.append((x, y, z, name, resname))
    return atoms


def centroid(pdbqt_path: Path) -> tuple[float, float, float, int]:
    coords = []
    with open(pdbqt_path, encoding="ascii", errors="ignore") as handle:
        for line in handle:
            if not line.startswith(("ATOM", "HETATM")):
                continue
            try:
                if line[77:79].strip() in ("HD", "H"):
                    continue
                coords.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
            except ValueError:
                continue
    if not coords:
        die(f"no hay átomos pesados en {pdbqt_path}")
    n = len(coords)
    return (sum(c[0] for c in coords) / n,
            sum(c[1] for c in coords) / n,
            sum(c[2] for c in coords) / n,
            n)


def main() -> int:
    parser = argparse.ArgumentParser(description="Calcula el centro de la caja de docking")
    parser.add_argument("--receptor", required=True, help="receptor PDBQT")
    parser.add_argument("--out", required=True, help="box.json de salida")
    parser.add_argument("--mode", choices=("mutation", "centroid", "binding-site"),
                        default="mutation")
    parser.add_argument("--mutation-pos", type=int, help="posición 1-based en la proteína")
    parser.add_argument("--model-start", type=int, default=1,
                        help="primer residuo proteico presente en el modelo")
    parser.add_argument("--expected-aa", help="aminoácido esperado en esa posición (1 letra)")
    parser.add_argument("--center", nargs=3, type=float, metavar=("X", "Y", "Z"),
                        help="centro explícito (mode=binding-site)")
    parser.add_argument("--box-size", type=float, default=25.0)
    args = parser.parse_args()

    receptor = Path(args.receptor)
    if not receptor.exists():
        die(f"no existe el receptor: {receptor}")

    result = {
        "box_size": args.box_size,
        "mode": args.mode,
        "receptor": receptor.name,
    }

    if args.mode == "binding-site":
        if not args.center:
            die("mode=binding-site requiere --center X Y Z")
        cx, cy, cz = args.center
        result.update(center_x=round(cx, 3), center_y=round(cy, 3), center_z=round(cz, 3))
    elif args.mode == "centroid":
        cx, cy, cz, n = centroid(receptor)
        result.update(center_x=round(cx, 3), center_y=round(cy, 3), center_z=round(cz, 3),
                      atoms_used=n)
    else:
        if args.mutation_pos is None:
            die("mode=mutation requiere --mutation-pos")
        if args.model_start < 1:
            die(f"--model-start inválido: {args.model_start}")
        rng = residue_range(receptor)
        if not rng:
            die(f"el receptor no tiene residuos: {receptor.name}")
        model_resseq_start = rng[0]
        model_resseq = model_resseq_start + (args.mutation_pos - args.model_start)
        atoms = read_residue_atoms(receptor, model_resseq)
        if not atoms:
            rango = f"{rng[0]}..{rng[1]}"
            die(
                f"el residuo {args.mutation_pos} (modelo: {model_resseq}) no existe en "
                f"{receptor.name}; residuos disponibles: {rango}. "
                f"Revisa --model-start={args.model_start}."
            )
        resname = atoms[0][4]
        if args.expected_aa:
            expected = args.expected_aa.upper()
            if expected not in AA3:
                die(f"--expected-aa inválido: {args.expected_aa}")
            if AA3_TO_1.get(resname) != expected:
                die(
                    f"residuo {args.mutation_pos} es {resname} "
                    f"({AA3_TO_1.get(resname, '?')}), se esperaba {expected} "
                    f"({args.expected_aa}). Estructura o --model-start incorrectos."
                )
        n = len(atoms)
        cx = sum(a[0] for a in atoms) / n
        cy = sum(a[1] for a in atoms) / n
        cz = sum(a[2] for a in atoms) / n
        result.update(
            center_x=round(cx, 3),
            center_y=round(cy, 3),
            center_z=round(cz, 3),
            mutation_pos=args.mutation_pos,
            model_start=args.model_start,
            model_resseq=model_resseq,
            model_resseq_start=model_resseq_start,
            residue=resname,
            atoms_used=n,
        )

    write_json(args.out, result, sort_keys=True)
    print(f"OK caja: ({result['center_x']}, {result['center_y']}, {result['center_z']}) "
          f"tamaño {result['box_size']} Å")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
