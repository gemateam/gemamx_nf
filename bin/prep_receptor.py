#!/usr/bin/env python3
"""PREP_RECEPTOR — PDB/CIF -> PDBQT rígido para AutoDock Vina.

OpenBabel añade hidrógenos y protona a pH fisiológico; después se escribe el
PDBQT por columnas exactas (enfoque "quirúrgico" del legado, más estable que
la conversión directa de OpenBabel). Los tipos AD4 se derivan del elemento,
no del nombre del átomo.

Reproducibilidad: OpenBabel 3.2.1 coloca algunos hidrógenos de forma aleatoria
cuando se usa `-p` (se detectaron dos amidas cerca de extremos de cadena). Con
`OB_RANDOM_SEED` fijo la salida es determinista; además se ejecuta dos veces y
se comparan los bytes: si difieren, el proceso falla en vez de publicar un
receptor irreproducible.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import die, sha256_file, write_json  # noqa: E402

AD4_TYPE = {
    "H": "HD", "C": "C", "N": "N", "O": "O", "S": "S", "P": "P", "F": "F",
    "CL": "Cl", "BR": "Br", "I": "I", "SE": "SE", "FE": "Fe", "ZN": "Zn",
    "MG": "Mg", "MN": "Mn", "CA": "Ca", "NA": "Na", "K": "K",
}

WATER_NAMES = {"HOH", "WAT", "DOD"}


def obabel_version() -> str:
    try:
        out = subprocess.run(["obabel", "-V"], capture_output=True, text=True, timeout=60)
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except Exception:  # noqa: BLE001
        return "desconocida"


def clean_with_obabel(source: Path, target: Path, ph: float, seed: int) -> None:
    """Convierte con OpenBabel y exige que dos ejecuciones den el mismo archivo."""
    cmd = ["obabel", str(source), "-O", str(target), "--addh", "-p", f"{ph:g}"]
    env = {**os.environ, "OB_RANDOM_SEED": str(seed)}

    def run_once(dest: Path) -> subprocess.CompletedProcess:
        local_cmd = [arg.replace(str(target), str(dest), 1) if arg == str(target) else arg
                     for arg in cmd]
        try:
            return subprocess.run(local_cmd, capture_output=True, text=True,
                                  timeout=600, env=env)
        except FileNotFoundError:
            die("obabel no está instalado en la imagen")
        except subprocess.TimeoutExpired:
            die(f"obabel excedió el tiempo límite procesando {source.name}")

    result = run_once(target)
    if not target.exists() or target.stat().st_size == 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-3:]
        die(f"obabel no generó {target.name}: " + " | ".join(tail))

    check = target.with_name(target.stem + "_check" + target.suffix)
    run_once(check)
    if not check.exists() or check.read_bytes() != target.read_bytes():
        check.unlink(missing_ok=True)
        die(
            f"OpenBabel no es determinista con OB_RANDOM_SEED={seed} al procesar "
            f"{source.name}; no se publica un receptor irreproducible."
        )
    check.unlink(missing_ok=True)


def element_of(line: str, atom_name: str) -> str:
    element = line[76:78].strip().upper()
    if element:
        return element
    # Fallback: primer carácter alfabético del nombre (p. ej. " CA " -> C)
    stripped = atom_name.lstrip("0123456789")
    return stripped[:1].upper() or "C"


def pdbqt_line(serial: int, name: str, resname: str, chain: str, resseq: int,
               x: float, y: float, z: float, ad4: str) -> str:
    line = f"ATOM  {serial:5d} "
    line += f"{name:<4}"[:4] + " "
    line += f"{resname:>3}"[:3] + " "
    line += f"{chain:1}" + f"{resseq:4d}" + "    "
    line += f"{x:8.3f}{y:8.3f}{z:8.3f}"
    line += f"{1.0:6.2f}{0.0:6.2f}    {0.0:6.3f} "
    line += f"{ad4:>2}"
    return line


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepara un receptor PDBQT")
    parser.add_argument("--structure", required=True, help="PDB o CIF de entrada")
    parser.add_argument("--out", required=True, help="PDBQT de salida")
    parser.add_argument("--meta", required=True, help="JSON con metadatos")
    parser.add_argument("--ph", type=float, default=7.4)
    parser.add_argument("--seed", type=int, default=42,
                        help="semilla de OpenBabel (OB_RANDOM_SEED)")
    parser.add_argument("--strip-hetatm", action="store_true", default=True,
                        help="descarta HETATM (aguas, ligandos cocristalizados)")
    parser.add_argument("--keep-hetatm", dest="strip_hetatm", action="store_false")
    args = parser.parse_args()

    source = Path(args.structure)
    if not source.exists():
        die(f"no existe la estructura: {source}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cleaned = out.with_name(out.stem + "_clean.pdb")
    clean_with_obabel(source, cleaned, args.ph, args.seed)

    atoms: list[dict] = []
    residues: set[tuple[str, int]] = set()
    chains: set[str] = set()
    elements: Counter[str] = Counter()

    with open(cleaned, encoding="ascii", errors="ignore") as handle:
        for raw in handle:
            if not raw.startswith(("ATOM", "HETATM")):
                continue
            if raw.startswith("HETATM") and args.strip_hetatm:
                continue
            altloc = raw[16]
            if altloc not in (" ", "A"):
                continue
            resname = raw[17:20].strip()
            if resname in WATER_NAMES:
                continue
            name = raw[12:16].strip()
            if not name:
                continue
            try:
                resseq = int(raw[22:26])
                x, y, z = float(raw[30:38]), float(raw[38:46]), float(raw[46:54])
            except ValueError:
                continue
            chain = raw[21] if raw[21].strip() else "A"
            element = element_of(raw, name)
            elements[element] += 1
            residues.add((chain, resseq))
            chains.add(chain)
            atoms.append({
                "name": name, "resname": resname, "chain": chain, "resseq": resseq,
                "x": x, "y": y, "z": z, "element": element,
            })

    if not atoms:
        die(f"la estructura {source.name} no tiene átomos utilizables")

    # Los hidrógenos polares (unidos a N/O/S) deben ir como tipo H; los unidos
    # a carbono, como HD. El elemento por sí solo no lo distingue (el legado
    # asignaba HD a todos, perdiendo donadores de puente de hidrógeno).
    heavy = [(a["x"], a["y"], a["z"], a["element"]) for a in atoms if a["element"] != "H"]
    polar_hydrogens = 0
    lines: list[str] = []
    for index, atom in enumerate(atoms, start=1):
        if atom["element"] == "H":
            nearest, best = None, 2.0
            for hx, hy, hz, hel in heavy:
                dist2 = (atom["x"] - hx) ** 2 + (atom["y"] - hy) ** 2 + (atom["z"] - hz) ** 2
                if dist2 < best:
                    best, nearest = dist2, hel
            if nearest in {"N", "O", "S"}:
                ad4 = "H"
                polar_hydrogens += 1
            else:
                ad4 = "HD"
        else:
            ad4 = AD4_TYPE.get(atom["element"], atom["element"][:2].title())
        lines.append(pdbqt_line(
            index, atom["name"], atom["resname"], atom["chain"], atom["resseq"],
            atom["x"], atom["y"], atom["z"], ad4,
        ))

    if len(lines) < 50:
        die(f"receptor sospechosamente pequeño: {len(lines)} átomos")

    out.write_text("\n".join(lines) + "\nTER\nEND\n", encoding="ascii", newline="\n")

    meta = {
        "structure": source.name,
        "structure_sha256": sha256_file(source),
        "pdbqt_file": out.name,
        "pdbqt_sha256": sha256_file(out),
        "atoms": len(lines),
        "residues": len(residues),
        "chains": sorted(chains),
        "elements": dict(sorted(elements.items())),
        "polar_hydrogens": polar_hydrogens,
        "ph": args.ph,
        "ob_random_seed": args.seed,
        "deterministic_check": True,
        "strip_hetatm": args.strip_hetatm,
        "obabel": obabel_version(),
    }
    write_json(args.meta, meta, sort_keys=True)
    print(f"OK receptor: {len(lines)} átomos ({polar_hydrogens} H polares), "
          f"{len(residues)} residuos -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
