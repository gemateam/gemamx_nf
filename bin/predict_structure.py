#!/usr/bin/env python3
"""PREDICT_STRUCTURE — una secuencia, una estructura, con pLDDT y ventana.

Backends:
  - esmfold     : API pública de ESMFold (sin GPU). Secuencias > 390 aa se
                  recortan a una ventana alrededor de la mutación (o de
                  `--window-center`, que es como el WT cubre la misma región
                  que el MUT) y el sidecar registra start/end para aplicar el
                  offset aguas abajo.
  - precomputed : copia una estructura existente y calcula su pLDDT. Si la
                  entrada es CIF/mmCIF se convierte a PDB: la salida de este
                  proceso es siempre un `.pdb`.

El sidecar JSON es obligatorio: sin `model_start` no se puede traducir la
posición proteica al resSeq del modelo. En `precomputed`, si no se pasa
`--model-start`, se lee del sidecar hermano (`<estructura>.json`) y, si no
existe, se asume que la estructura conserva la numeración de la proteína
(`model_start = primer resSeq observado`).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import requests
from Bio.PDB import MMCIFParser, MMCIFIO, PDBIO, PDBParser
from Bio.PDB.Polypeptide import protein_letters_3to1

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import (  # noqa: E402
    AA3_TO_1, die, parse_mutation, read_fasta, sha256_file, sha256_text, write_json,
)

ESMFOLD_URL = "https://api.esmatlas.com/foldSequence/v1/pdb/"
ESMFOLD_LIMIT = 390
CIF_SUFFIXES = {".cif", ".mmcif"}

PARSERS = {".pdb": PDBParser, ".ent": PDBParser, ".cif": MMCIFParser, ".mmcif": MMCIFParser}


def convert_to_pdb(source: Path, target: Path) -> None:
    """Escribe `target` como PDB. Sólo convierte si la entrada es CIF/mmCIF."""
    if source.suffix.lower() not in CIF_SUFFIXES:
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        return
    parser = MMCIFParser(QUIET=True)
    structure = parser.get_structure("model", str(source))
    writer = PDBIO()
    writer.set_structure(structure)
    writer.save(str(target))
    if not target.is_file() or target.stat().st_size == 0:
        die(f"la conversión CIF->PDB de {source.name} no produjo salida")


def convert_pdb_to_cif(pdb_path: Path, cif_path: Path) -> None:
    """Convierte un PDB a mmCIF mínimo. Molstar v3 parsea mmCIF de forma nativa
    y más robusta que PDB (evita el 'TypeError: entry' con fragmentos sin CRYST1)."""
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("model", str(pdb_path))
    writer = MMCIFIO()
    writer.set_structure(structure)
    writer.save(str(cif_path))
    if not cif_path.is_file() or cif_path.stat().st_size == 0:
        die(f"la conversión PDB->CIF de {pdb_path.name} no produjo salida")


def sidecar_model_start(source: Path) -> int | None:
    """Lee `model_start` del sidecar hermano `<estructura>.json`, si existe."""
    candidate = source.with_suffix(".json")
    if not candidate.is_file():
        return None
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and data.get("model_start") is not None:
        return int(data["model_start"])
    return None


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


def fasta_model_start(sequence: str, residues: list[dict]) -> int | None:
    """Posición 1-based del modelo dentro de la secuencia completa.

    Sólo devuelve un valor si los residuos son contiguos, no hay `X` y la
    secuencia del modelo aparece exactamente una vez en la proteína. Sirve
    para detectar un `model_start` de sidecar incoherente (p. ej. tras
    renumerar un PDB fragmento desde 1).
    """
    if not residues:
        return None
    positions = [r["resseq"] for r in residues]
    if positions != list(range(positions[0], positions[-1] + 1)):
        return None
    model_seq = "".join(r["one"] for r in residues)
    if not model_seq or "X" in model_seq:
        return None
    first, last = sequence.find(model_seq), sequence.rfind(model_seq)
    if first == -1 or first != last:
        return None
    return first + 1


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
    parser.add_argument("--model-start", type=int,
                        help="primer residuo proteico del modelo (precomputed; "
                             "por defecto, sidecar hermano o primer resSeq)")
    parser.add_argument("--out-cif", help="ruta de salida mmCIF adicional (para la webapp)")
    parser.add_argument("--window", type=int, default=180)
    parser.add_argument("--window-center", type=int,
                        help="posición proteica sobre la que centrar la ventana "
                             "de ESMFold en WT (por defecto, la mutación)")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args()

    gene = args.gene.strip().upper()
    change = args.protein_change.strip().upper()
    mutation = None if change == "WT" else parse_mutation(change)
    mutation_pos = mutation[1] if mutation else None

    _, sequence = read_fasta(args.fasta)
    out = Path(args.out)
    if out.suffix.lower() != ".pdb":
        die(f"--out debe terminar en .pdb (estructura normalizada): {out}")
    out.parent.mkdir(parents=True, exist_ok=True)

    meta: dict = {
        "gene": gene,
        "protein_change": change,
        "role": args.role,
        "backend": args.backend,
        "fasta_length": len(sequence),
        "fasta_sha256": sha256_text(sequence),
    }
    model_start: int | None = None

    if args.backend == "esmfold":
        if len(sequence) <= ESMFOLD_LIMIT:
            model_start, model_end = 1, len(sequence)
            model_seq = sequence
        else:
            # WT no tiene posición de mutación propia: se centra la ventana en
            # --window-center (la del evento que se compara) para que WT y MUT
            # cubran la misma región y el RMSD sea comparable.
            center = mutation_pos if mutation_pos is not None else args.window_center
            if center is None:
                die(f"{gene}: secuencia de {len(sequence)} aa sin posición de mutación "
                    f"ni --window-center para recortar la ventana")
            if not 1 <= center <= len(sequence):
                die(f"--window-center fuera de rango: {center} (1..{len(sequence)})")
            if args.window < 20:
                die(f"--window demasiado pequeño: {args.window}")
            model_start = max(1, center - args.window)
            model_end = min(len(sequence), center + args.window - 1)
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
        convert_to_pdb(source_path, out)
        model_start = args.model_start
        meta.update(
            source=source_path.name,
            source_format=source_path.suffix.lower().lstrip("."),
            source_sha256=sha256_file(source_path),
        )

    residues = load_ca(out)
    positions = [r["resseq"] for r in residues]
    observed_start, observed_end = min(positions), max(positions)

    if model_start is None:
        if args.backend == "precomputed":
            model_start = sidecar_model_start(Path(args.structure)) or observed_start
        else:
            model_start = observed_start
    if model_start < 1:
        die(f"model_start inválido: {model_start}")

    # En precomputed, si el modelo es un fragmento identificable en la proteína,
    # la secuencia manda: un sidecar con model_start incoherente (típico tras
    # renumerar el PDB desde 1) desplazaría la mutación al resSeq equivocado.
    if args.backend == "precomputed":
        inferred_start = fasta_model_start(sequence, residues)
        if inferred_start is not None and inferred_start != model_start:
            print(f"WARN: {out.name}: model_start={model_start} no coincide con la "
                  f"secuencia de la proteína (el modelo empieza en {inferred_start}); "
                  f"se usa {inferred_start}. Revisa el sidecar de la estructura "
                  f"precomputada.", file=sys.stderr)
            model_start = inferred_start
            meta["model_start_source"] = "fasta_alignment"

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

    # Generar mmCIF adicional para la webapp (Molstar v3 lo parsea sin errores)
    if args.out_cif:
        cif_out = Path(args.out_cif)
        cif_out.parent.mkdir(parents=True, exist_ok=True)
        convert_pdb_to_cif(out, cif_out)
        meta["structure_cif"] = cif_out.name
        write_json(args.meta, meta, sort_keys=True)  # actualizar sidecar con cif
        print(f"  cif: {cif_out.name} ({cif_out.stat().st_size // 1024} KB)")

    print(f"OK estructura {out.name}: {len(residues)} residuos, "
          f"pLDDT {meta['plddt_mean']}, modelo {meta['model_start']}..{meta['model_end']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
