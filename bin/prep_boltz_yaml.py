#!/usr/bin/env python3
"""BOLTZ — prepara la entrada YAML de Boltz-1 (no ejecuta Boltz, no usa GPU).

Boltz-1 recibe un YAML con la secuencia (una cadena `A` en este pipeline).
Este script:

  1. aplica la mutación sobre la secuencia WT cuando `--role mut`;
  2. recorta la misma ventana (± `--window`) que usa ESMFold para proteínas
     largas, de modo que WT y MUT cubran la misma región y el RMSD sea
     comparable con `precomputed`;
  3. escribe el YAML de Boltz y un sidecar con `model_start` / `model_end` y el
     resSeq esperado de la mutación.

Se puede ejecutar y probar sin GPU: solo prepara el fichero de entrada.

Uso:
  prep_boltz_yaml.py --fasta PIK3CA.fasta --gene PIK3CA --role wt \\
      --window-center 1047 --out-yaml wt.yaml --out-meta wt_prep.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import die, parse_mutation, read_fasta, write_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepara el YAML de entrada de Boltz-1")
    parser.add_argument("--fasta", required=True)
    parser.add_argument("--gene", required=True)
    parser.add_argument("--protein-change", default="WT")
    parser.add_argument("--role", choices=("wt", "mut"), required=True)
    parser.add_argument("--out-yaml", required=True)
    parser.add_argument("--out-meta", required=True)
    parser.add_argument("--window", type=int, default=180,
                        help="ventana ± residuos para proteínas largas (0 = completa)")
    parser.add_argument("--window-center", type=int,
                        help="posición proteica del centro de la ventana en WT")
    parser.add_argument("--chain-id", default="A")
    parser.add_argument("--job-name", default="boltz")
    args = parser.parse_args()

    gene = args.gene.strip().upper()
    change = args.protein_change.strip().upper()
    mutation = None if change == "WT" else parse_mutation(change)
    mutation_pos = mutation[1] if mutation else None

    _, sequence = read_fasta(args.fasta)
    if not sequence:
        die(f"{gene}: FASTA vacío")

    total = len(sequence)
    center = mutation_pos if mutation_pos is not None else args.window_center

    if args.window > 0 and center is not None and total > 2 * args.window + 1:
        if not 1 <= center <= total:
            die(f"--window-center fuera de rango: {center} (1..{total})")
        model_start = max(1, center - args.window)
        model_end = min(total, center + args.window - 1)
    else:
        model_start, model_end = 1, total
    model_seq = sequence[model_start - 1:model_end]

    meta = {
        "gene": gene,
        "protein_change": change,
        "role": args.role,
        "backend": "boltz",
        "fasta_length": total,
        "model_start": model_start,
        "model_end": model_end,
        "model_length": len(model_seq),
        "mutation_pos": mutation_pos,
        "mutation_resseq_model": None,
    }

    if mutation is not None:
        wt_aa, position, mut_aa = mutation
        if not model_start <= position <= model_end:
            die(f"{gene} {change}: la mutación {position} queda fuera de la ventana "
                f"{model_start}..{model_end}")
        index = position - model_start
        observed = model_seq[index]
        if observed != wt_aa:
            die(f"{gene} {change}: la posición {position} es {observed} en el FASTA, "
                f"se esperaba {wt_aa}")
        # Boltz predice la secuencia MUT: se sustituye el residuo antes de plegar.
        model_seq = model_seq[:index] + mut_aa + model_seq[index + 1:]
        meta["mutation_resseq_model"] = index + 1
        meta["expected_aa"] = mut_aa
    elif args.role == "mut":
        die("role=mut requiere --protein-change con formato H1047R")

    yaml_text = (
        "version: 1\n"
        "sequences:\n"
        "  - protein:\n"
        f"      id: {args.chain_id}\n"
        f"      sequence: \"{model_seq}\"\n"
        "      msa: empty\n"
    )
    out_yaml = Path(args.out_yaml)
    out_yaml.parent.mkdir(parents=True, exist_ok=True)
    out_yaml.write_text(yaml_text, encoding="ascii", newline="\n")
    write_json(args.out_meta, meta, sort_keys=True)

    print(f"OK Boltz YAML {out_yaml.name}: {len(model_seq)} aa "
          f"(modelo {model_start}..{model_end}), mutación {meta['mutation_resseq_model']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
