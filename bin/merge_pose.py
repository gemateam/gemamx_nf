#!/usr/bin/env python3
"""MERGE_POSE — receptor + pose 1 de Vina -> PDB de complejo.

La app web pide `data/docking/complex/<var>_<drug>_complex.pdb` (se comprueba
con HEAD). El PDB se escribe con columnas estrictas 3.30 para que Molstar lo
renderice: cadena A = proteína, cadena L = ligando (pose 1).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import die  # noqa: E402

AD4_TO_ELEMENT = {
    "C": "C", "A": "C", "CA": "C",
    "N": "N", "NA": "N", "NS": "N",
    "O": "O", "OA": "O", "OS": "O",
    "H": "H", "HD": "H", "HS": "H",
    "S": "S", "SA": "S",
    "F": "F", "CL": "CL", "BR": "BR", "I": "I",
    "P": "P", "FE": "FE", "ZN": "ZN", "MG": "MG", "MN": "MN", "SE": "SE",
}


def element_from_ad4(ad4: str) -> str:
    key = ad4.strip().upper()
    return AD4_TO_ELEMENT.get(key, key[:1] or "C")


def format_atom_name(name: str, element: str) -> str:
    name = name.strip()
    if len(element.strip()) == 1:
        return f" {name:<3}" if len(name) <= 3 else name[:4]
    return f"{name:<4}"


def pdb_line(record: str, serial: int, atom_name: str, resname: str, chain: str,
             resseq: int, x: float, y: float, z: float, element: str) -> str:
    return (
        f"{record:<6}{serial:5d} {format_atom_name(atom_name, element)} "
        f"{resname:>3} {chain[:1]}{resseq:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {element.strip():>2}"
    )[:80]


def receptor_lines(pdbqt: Path) -> list[str]:
    lines = []
    serial = 0
    with open(pdbqt, encoding="ascii", errors="ignore") as handle:
        for line in handle:
            if not line.startswith(("ATOM", "HETATM")):
                continue
            try:
                name = line[12:16].strip()
                resname = line[17:20].strip() or "UNK"
                resseq = int(line[22:26])
                x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
            except ValueError:
                continue
            ad4 = line[77:79].strip() if len(line) > 77 else name[:1]
            element = element_from_ad4(ad4)
            serial += 1
            lines.append(pdb_line("ATOM", serial, name, resname, "A", resseq, x, y, z, element))
    return lines


def ligand_model1_lines(pdbqt: Path) -> list[str]:
    lines = []
    in_model = False
    base_serial = 10000
    with open(pdbqt, encoding="ascii", errors="ignore") as handle:
        for line in handle:
            if line.startswith("MODEL"):
                # Algunos writers no numeran: el primer MODEL es la pose 1.
                in_model = "MODEL 1" in line or (not lines and "MODEL" in line)
                if not in_model:
                    continue
            if line.startswith("ENDMDL") and in_model:
                break
            if not in_model or not line.startswith(("ATOM", "HETATM")):
                continue
            try:
                name = line[12:16].strip()
                x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
            except ValueError:
                continue
            ad4 = line[77:79].strip() if len(line) > 77 else name[:1]
            element = element_from_ad4(ad4)
            serial = base_serial + len(lines) + 1
            lines.append(pdb_line("HETATM", serial, name, "LIG", "L", 1, x, y, z, element))
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera el PDB del complejo receptor + pose 1")
    parser.add_argument("--receptor-pdbqt", required=True)
    parser.add_argument("--ligand-out-pdbqt", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    receptor = Path(args.receptor_pdbqt)
    ligand = Path(args.ligand_out_pdbqt)
    for label, path in (("receptor", receptor), ("poses", ligand)):
        if not path.exists():
            die(f"no existe el {label}: {path}")

    rec = receptor_lines(receptor)
    lig = ligand_model1_lines(ligand)
    if not rec:
        die(f"el receptor PDBQT no tiene átomos: {receptor}")
    if not lig:
        die(f"la pose PDBQT no tiene átomos en el MODEL 1: {ligand}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="ascii", newline="\n") as handle:
        handle.write("REMARK GEMA MX complex\n")
        handle.write(f"REMARK Receptor: {receptor.name}\n")
        handle.write(f"REMARK Ligand:   {ligand.name}\n")
        handle.write("REMARK Chain A = protein | Chain L = ligand (Vina pose 1)\n")
        handle.write("\n".join(rec) + "\n")
        handle.write("TER\n")
        handle.write("\n".join(lig) + "\n")
        handle.write("END\n")

    print(f"OK complejo: {len(rec)} átomos de receptor + {len(lig)} de ligando -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
