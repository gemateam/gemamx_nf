#!/usr/bin/env python3
"""Utilidades compartidas por los scripts CLI de gemamx_nf.

Sin dependencias externas: solo stdlib. Los scripts de `bin/` se ejecutan
dentro de las imágenes de la plataforma y se importan entre sí cuando hace
falta reutilizar lógica (p. ej. el parser de logs de Vina).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

# Aminoácidos: 1 letra -> 3 letras (para validar residuos en estructuras)
AA3 = {
    "A": "ALA", "R": "ARG", "N": "ASN", "D": "ASP", "C": "CYS",
    "Q": "GLN", "E": "GLU", "G": "GLY", "H": "HIS", "I": "ILE",
    "L": "LEU", "K": "LYS", "M": "MET", "F": "PHE", "P": "PRO",
    "S": "SER", "T": "THR", "W": "TRP", "Y": "TYR", "V": "VAL",
}
AA3_TO_1 = {v: k for k, v in AA3.items()}

MUTATION_RE = re.compile(r"^([A-Z])(\d+)([A-Z])$")
VARIANT_RE = re.compile(r"^([A-Za-z0-9]+)_([A-Z])(\d+)([A-Z])$")


def die(message: str, code: int = 1) -> "NoReturn":
    """Falla con un mensaje legible (sin traceback) y código distinto de cero."""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def parse_mutation(change: str) -> tuple[str, int, str]:
    """'H1047R' -> ('H', 1047, 'R'). Falla si el formato no es válido."""
    match = MUTATION_RE.match(change.strip())
    if not match:
        die(f"cambio proteico inválido: {change!r} (se espera p. ej. H1047R)")
    return match.group(1), int(match.group(2)), match.group(3)


def parse_variant(variant_id: str) -> tuple[str, str, int, str]:
    """'PIK3CA_H1047R' -> ('PIK3CA', 'H', 1047, 'R')."""
    match = VARIANT_RE.match(variant_id.strip())
    if not match:
        die(f"identificador de variante inválido: {variant_id!r}")
    return match.group(1), match.group(2), int(match.group(3)), match.group(4)


def read_json(path: str | Path) -> object:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        die(f"no existe el archivo: {path}")
    except json.JSONDecodeError as exc:
        die(f"JSON inválido en {path}: {exc}")


def write_json(path: str | Path, data: object, sort_keys: bool = False,
               indent: int | None = 4) -> None:
    """Escribe JSON determinista (UTF-8, sin escapar acentos, salto final).

    `indent=None` produce JSON compacto (mismo contenido, menos bytes).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if indent is None:
        text = json.dumps(data, ensure_ascii=False, sort_keys=sort_keys,
                          separators=(",", ":"))
    else:
        text = json.dumps(data, indent=indent, ensure_ascii=False, sort_keys=sort_keys)
    path.write_text(text + "\n", encoding="utf-8")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_fasta(path: str | Path) -> tuple[str, str]:
    """Lee un FASTA de una sola secuencia -> (header, secuencia)."""
    header = ""
    chunks: list[str] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if header:
                    die(f"FASTA con más de una secuencia: {path}")
                header = line[1:].strip()
            else:
                chunks.append(line)
    if not chunks:
        die(f"FASTA vacío: {path}")
    return header, "".join(chunks).upper()


def residue_range(pdbqt_path: str | Path) -> tuple[int, int] | None:
    """Rango de resSeq presente en un PDB/PDBQT (None si no hay ATOM)."""
    values: list[int] = []
    with open(pdbqt_path, encoding="ascii", errors="ignore") as handle:
        for line in handle:
            if line.startswith(("ATOM", "HETATM")):
                try:
                    values.append(int(line[22:26]))
                except ValueError:
                    continue
    return (min(values), max(values)) if values else None
