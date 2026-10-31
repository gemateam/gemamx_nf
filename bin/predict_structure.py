#!/usr/bin/env python3
"""PREDICT_STRUCTURE — una secuencia, una estructura, con pLDDT y ventana.

Backends:
  - esmfold     : API pública de ESMFold (sin GPU). Secuencias > 390 aa se
                  recortan a una ventana alrededor de la mutación y el sidecar
                  registra start/end para aplicar el offset aguas abajo.
  - precomputed : copia una estructura existente y calcula su pLDDT.

El sidecar JSON es obligatorio: sin `model_start` no se puede traducir la
posición proteica al resSeq del modelo.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests
from Bio.PDB import MMCIFParser, PDBParser
from Bio.PDB.Polypeptide import protein_letters_3to1

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import (  # noqa: E402
    AA3_TO_1, die, parse_mutation, read_fasta, sha256_file, sha256_text, write_json,
)

ESMFOLD_URL = "https://api.esmatlas.com/foldSequence/v1/pdb/"
ESMFOLD_LIMIT = 390

PARSERS = {".pdb": PDBParser, ".ent": PDBParser, ".cif": MMCIFParser, ".mmcif": MMCIFParser}


def load_ca(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    parser_class = PARSERS.get(suffix)
    if parser_class is None:
        die(f"formato de estructura no soportado: {path.suffix}")
    parser = parser_class(QUIET=True)
    structure = parser.get_structure("model", str(path))
    residues = []
    for model in structure:
        for chain in model:
            for residue in chain:
                if "CA" not in residue:
                    continue
                name = residue.get_resname().strip().upper()
                one = AA3_TO_1.get(name) or protein_letters_3to1.get(name, "X")
                residues.append({
                    "resseq": residue.id[1],
                    "resname": name,
                    "one": one,
                    "bfactor": float(residue["CA"].get_bfactor()),
                    "coord": tuple(float(v) for v in residue["CA"].get_coord()),
                })
        break  # solo el primer modelo
    if not residues:
        die(f"la estructura {path.name} no tiene átomos CA")
    return residues


def fold_with_esmfold(sequence: str, timeout: int, retries: int) -> str:
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    last_error = None
    for attempt in range(retries):
        try:
            response = requests.post(ESMFOLD_URL, headers=headers, data=sequence,
                                     timeout=timeout)
            if response.status_code == 200 and "ATOM" in response.text:
                return response.text
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(5 * (attempt + 1))
    die(f"ESMFold no devolvió una estructura: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Predice o importa una estructura")
    parser.add_argument("--fasta", required=True)
    parser.add_argument("--gene", required=True)
    parser.add_argument("--protein-change", default="WT")
    parser.add_argument("--role", choices=("wt", "mut"), required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--meta", required=True)
    parser.add_argument("--backend", choices=("esmfold", "precomputed"), default="esmfold")
    parser.add_argument("--structure", help="estructura de entrada (precomputed)")
    parser.add_argument("--model-start", type=int, default=1,
                        help="primer residuo proteico del modelo (precomputed)")
    parser.add_argument("--window", type=int, default=180)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args()

    gene = args.gene.strip().upper()
    change = args.protein_change.strip().upper()
    mutation = None if change == "WT" else parse_mutation(change)
    mutation_pos = mutation[1] if mutation else None

    _, sequence = read_fasta(args.fasta)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    meta: dict = {
        "gene": gene,
        "protein_change": change,
        "role": args.role,
        "backend": args.backend,
        "fasta_length": len(sequence),
        "fasta_sha256": sha256_text(sequence),
    }

    if args.backend == "esmfold":
        if len(sequence) <= ESMFOLD_LIMIT:
            model_start, model_end = 1, len(sequence)
            model_seq = sequence
        else:
            if mutation_pos is None:
                die(f"{gene}: secuencia de {len(sequence)} aa sin posición de mutación "
                    f"para recortar la ventana")
            if args.window < 20:
                die(f"--window demasiado pequeño: {args.window}")
            model_start = max(1, mutation_pos - args.window)
            model_end = min(len(sequence), mutation_pos + args.window - 1)
            model_seq = sequence[model_start - 1:model_end]
        if len(model_seq) > ESMFOLD_LIMIT:
            die(f"ventana de {len(model_seq)} aa supera el límite de ESMFold ({ESMFOLD_LIMIT})")
        structure_text = fold_with_esmfold(model_seq, args.timeout, args.retries)
        out.write_text(structure_text, encoding="ascii", newline="\n")
        meta.update(model_start=model_start, model_end=model_end,
                    model_length=len(model_seq), source="ESMFold API")
    else:
        if not args.structure:
            die("backend=precomputed requiere --structure")
        source_path = Path(args.structure)
        if not source_path.exists():
            die(f"no existe la estructura: {source_path}")
        out.write_bytes(source_path.read_bytes())
        model_start = args.model_start
        meta.update(
            model_start=model_start,
            model_end=None,
            model_length=None,
            source=source_path.name,
            source_sha256=sha256_file(source_path),
        )

    residues = load_ca(out)
    positions = [r["resseq"] for r in residues]
    observed_start, observed_end = min(positions), max(positions)

    raw_bfactors = [r["bfactor"] for r in residues]
    # ESMFold (API) escribe pLDDT en 0..1; AlphaFold/Boltz en 0..100.
    scale = 100.0 if max(raw_bfactors) <= 1.5 else 1.0
    plddts = [value * scale for value in raw_bfactors]
    meta.update(
        plddt_mean=round(sum(plddts) / len(plddts), 1),
        plddt_min=round(min(plddts), 1),
        plddt_max=round(max(plddts), 1),
        residues=len(residues),
        model_start=model_start,
        model_resseq_start=observed_start,
        model_resseq_end=observed_end,
        model_end=model_start + (observed_end - observed_start),
        model_length=observed_end - observed_start + 1,
        structure_file=out.name,
        structure_sha256=sha256_file(out),
        format=out.suffix.lower().lstrip("."),
    )

    if mutation:
        wt_aa, position, mut_aa = mutation
        expected = wt_aa if args.role == "wt" else mut_aa
        model_resseq = observed_start + (position - model_start)
        meta.update(mutation_pos=position, mutation_resseq_model=model_resseq,
                    expected_aa=expected)
        match = next((r for r in residues if r["resseq"] == model_resseq), None)
        if match is None:
            die(f"{gene} {change}: el residuo {position} (modelo: {model_resseq}) "
                f"no está en la estructura (residuos {observed_start}..{observed_end})")
        if match["one"] != expected:
            die(f"{gene} {change}: residuo {position} es {match['resname']} "
                f"({match['one']}), se esperaba {expected} para role={args.role}")

    write_json(args.meta, meta, sort_keys=True)
    print(f"OK estructura {out.name}: {len(residues)} residuos, "
          f"pLDDT {meta['plddt_mean']}, modelo {meta['model_start']}..{meta['model_end']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
