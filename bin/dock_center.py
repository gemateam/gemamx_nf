#!/usr/bin/env python3
"""DOCK_CENTER — centro de la caja de Vina.

Corrige el defecto del legado: el modelo puede estar renumerado desde 1
(fragmento de ESMFold), así que la posición proteica se traduce al resSeq del
modelo con

    pos_modelo = resseq_inicial + (pos_proteína - model_start)

y el residuo se verifica (existe y, si se indica, coincide con el aminoácido
esperado). Si no se puede verificar, el proceso falla: no hay fallback
silencioso al centro de masa.

`--meta` permite leer `mutation_pos`, `model_start` y `expected_aa` del sidecar
de PREDICT_STRUCTURE, de modo que Nextflow no tenga que repetir esos valores y
no puedan desincronizarse. Los argumentos explícitos tienen prioridad.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import (  # noqa: E402
    AA3, AA3_TO_1, die, read_json, residue_range, write_json,
)


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
    parser.add_argument("--mode", choices=("mutation", "centroid", "binding-site", "site-residues"),
                        default="mutation")
    parser.add_argument("--site-residues",
                        help="residuos proteicos del sitio de union separados por ';' "
                             "(mode=site-residues); se traducen al resSeq del modelo")
    parser.add_argument("--on-missing", choices=("fail", "centroid"), default="fail",
                        help="mode=site-residues cuando el modelo no cubre el sitio: "
                             "fail (por defecto) o centroid (explícito; queda registrado "
                             "en el box.json como site_covered=false)")
    parser.add_argument("--meta", help="sidecar de PREDICT_STRUCTURE "
                                       "(mutation_pos, model_start, expected_aa)")
    parser.add_argument("--mutation-pos", type=int, help="posición 1-based en la proteína")
    parser.add_argument("--model-start", type=int,
                        help="primer residuo proteico del modelo (por defecto, el del --meta o 1)")
    parser.add_argument("--expected-aa", help="aminoácido esperado en esa posición (1 letra)")
    parser.add_argument("--center", nargs=3, type=float, metavar=("X", "Y", "Z"),
                        help="centro explícito (mode=binding-site)")
    parser.add_argument("--box-size", type=float, default=25.0)
    args = parser.parse_args()

    receptor = Path(args.receptor)
    if not receptor.exists():
        die(f"no existe el receptor: {receptor}")

    meta: dict = {}
    if args.meta:
        meta_path = Path(args.meta)
        if not meta_path.exists():
            die(f"no existe el sidecar: {meta_path}")
        meta = read_json(meta_path)
        if not isinstance(meta, dict):
            die(f"sidecar inválido: {meta_path}")

    if args.model_start is None:
        args.model_start = meta.get("model_start", 1)
    if args.mutation_pos is None and meta.get("mutation_pos") is not None:
        args.mutation_pos = int(meta["mutation_pos"])
    if not args.expected_aa and meta.get("expected_aa"):
        args.expected_aa = str(meta["expected_aa"])

    result = {
        "box_size": args.box_size,
        "mode": args.mode,
        "receptor": receptor.name,
    }
    if args.meta:
        result["meta"] = Path(args.meta).name

    if args.mode == "site-residues":
        if not args.site_residues:
            die("mode=site-residues requiere --site-residues")
        wanted = [int(v) for v in args.site_residues.replace(",", ";").split(";") if v.strip()]
        if args.model_start < 1:
            die(f"--model-start inválido: {args.model_start}")
        rng = residue_range(receptor)
        if not rng:
            die(f"el receptor no tiene residuos: {receptor.name}")
        coords = []
        missing = []
        for pos in wanted:
            resseq = rng[0] + (pos - args.model_start)
            atoms = read_residue_atoms(receptor, resseq)
            if not atoms:
                missing.append(pos)
                continue
            coords.extend((a[0], a[1], a[2]) for a in atoms)
        # Sin fallback silencioso: por defecto, si el fragmento no cubre el sitio, se falla.
        # Con --on-missing centroid el fallback es explícito y queda registrado.
        if missing and args.on_missing == "fail":
            die(f"{receptor.name}: el modelo (proteína {args.model_start}.. con resSeq "
                f"{rng[0]}..{rng[1]}) no contiene los residuos del sitio {missing}. "
                "El fragmento no cubre el bolsillo; usa un dominio completo.")
        if missing:
            cx, cy, cz, n = centroid(receptor)
            result.update(
                center_x=round(cx, 3),
                center_y=round(cy, 3),
                center_z=round(cz, 3),
                site_residues=wanted,
                site_covered=False,
                site_missing_residues=missing,
                fallback="centroid",
                model_start=args.model_start,
                atoms_used=n,
            )
        else:
            n = len(coords)
            result.update(
                center_x=round(sum(c[0] for c in coords) / n, 3),
                center_y=round(sum(c[1] for c in coords) / n, 3),
                center_z=round(sum(c[2] for c in coords) / n, 3),
                site_residues=wanted,
                site_covered=True,
                model_start=args.model_start,
                atoms_used=n,
            )
    elif args.mode == "binding-site":
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
        if meta.get("mutation_resseq_model") is not None:
            if int(meta["mutation_resseq_model"]) != model_resseq:
                die(
                    f"el sidecar indica mutation_resseq_model={meta['mutation_resseq_model']} "
                    f"pero con model_start={args.model_start} y el receptor actual "
                    f"(resseq inicial {model_resseq_start}) se obtiene {model_resseq}. "
                    "Sidecar y estructura no corresponden."
                )
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
