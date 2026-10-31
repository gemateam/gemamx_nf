#!/usr/bin/env python3
"""FETCH_FASTA — secuencia WT (UniProt) y, opcionalmente, la mutante.

Una invocación = una variante (o el WT de un gen). La mutación se valida:
si el residuo en la posición indicada no coincide con el aminoácido WT
declarado, el proceso falla (el legado solo avisaba y continuaba).

Salidas (en --outdir):
  <GEN>_WT.fasta      + <GEN>_WT.json
  <GEN>_<CAMBIO>.fasta + <GEN>_<CAMBIO>.json   (si --protein-change != WT)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import (  # noqa: E402
    die, parse_mutation, read_fasta, sha256_text, write_json,
)

UNIPROT_SEARCH = "https://rest.uniprot.org/uniprotkb/search"
UNIPROT_FASTA = "https://rest.uniprot.org/uniprotkb/{}.fasta"


def resolve_accession(gene: str) -> str:
    params = {
        "query": f"gene:{gene} AND organism_id:9606 AND reviewed:true",
        "fields": "accession",
        "format": "json",
        "size": 1,
    }
    try:
        response = requests.get(UNIPROT_SEARCH, params=params, timeout=60)
    except requests.RequestException as exc:
        die(f"fallo consultando UniProt para {gene}: {exc}")
    if response.status_code != 200:
        die(f"UniProt respondió {response.status_code} para {gene}")
    results = response.json().get("results") or []
    if not results:
        die(f"no hay entrada revisada de UniProt para {gene} (humano)")
    return results[0]["primaryAccession"]


def fetch_sequence(accession: str) -> str:
    try:
        response = requests.get(UNIPROT_FASTA.format(accession), timeout=120)
    except requests.RequestException as exc:
        die(f"fallo descargando {accession}: {exc}")
    if response.status_code != 200:
        die(f"UniProt respondió {response.status_code} para {accession}")
    lines = [line.strip() for line in response.text.splitlines()]
    sequence = "".join(line for line in lines if line and not line.startswith(">")).upper()
    if not sequence:
        die(f"secuencia vacía para {accession}")
    return sequence


def write_fasta(path: Path, header: str, sequence: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f">{header}\n{sequence}\n", encoding="ascii", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Obtiene FASTA WT y mutante de un gen")
    parser.add_argument("--gene", required=True)
    parser.add_argument("--protein-change", default="WT",
                        help="WT o cambio tipo H1047R")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--uniprot", help="accesión UniProt (si se conoce)")
    parser.add_argument("--wt-fasta", help="FASTA WT ya descargado (evita la red)")
    args = parser.parse_args()

    gene = args.gene.strip().upper()
    if not gene:
        die("--gene vacío")

    if args.wt_fasta:
        _, sequence = read_fasta(args.wt_fasta)
        accession = args.uniprot or "local"
        source = Path(args.wt_fasta).name
    else:
        accession = args.uniprot or resolve_accession(gene)
        sequence = fetch_sequence(accession)
        source = f"UniProt:{accession}"

    outdir = Path(args.outdir)
    specs = [
        ("WT", sequence, None),
    ]

    change = args.protein_change.strip().upper()
    if change != "WT":
        wt_aa, position, mut_aa = parse_mutation(change)
        if position > len(sequence):
            die(f"{gene} {change}: posición {position} fuera de la secuencia ({len(sequence)} aa)")
        observed = sequence[position - 1]
        if observed != wt_aa:
            die(
                f"{gene} {change}: se esperaba {wt_aa} en la posición {position}, "
                f"pero la secuencia tiene {observed}. UniProt {accession}."
            )
        mutant = sequence[:position - 1] + mut_aa + sequence[position:]
        if mutant == sequence:
            die(f"{gene} {change}: la mutación no cambia la secuencia")
        specs.append((change, mutant, (wt_aa, position, mut_aa)))

    for label, seq, mutation in specs:
        base = f"{gene}_{label}"
        fasta_path = outdir / f"{base}.fasta"
        write_fasta(fasta_path, f"{base} | {accession}", seq)
        meta = {
            "gene": gene,
            "protein_change": label,
            "uniprot_id": accession,
            "length": len(seq),
            "source": source,
            "sequence_sha256": sha256_text(seq),
        }
        if mutation:
            wt_aa, position, mut_aa = mutation
            meta.update(
                mutation_pos=position,
                wt_aa=wt_aa,
                mut_aa=mut_aa,
                mutation_index_0based=position - 1,
            )
        write_json(outdir / f"{base}.json", meta, sort_keys=True)
        print(f"OK {base}: {len(seq)} aa ({accession})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
