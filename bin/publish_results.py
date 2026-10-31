#!/usr/bin/env python3
"""PUBLISH — sella la corrida y construye el árbol de salida dentro del workdir.

Nextflow se encarga de copiar los outputs al host via publishDir.
Este script ya NO escribe directamente al outdir del host; solo construye:

  <workdir>/
    data/                  ← árbol de contrato (se publica a runs/<name>/data y a data/)
      top_variants.json
      structural_metrics.json
      manifest_structures.json
      raw_mutations.json
      mutation_stats.json
      docking/
        vina_affinities.json
        results/
        complex/
      structures/
    run_manifest.json      ← se publica a runs/<name>/ y a la raíz del outdir
    params.json            ← solo para MLflow (no se publica al host)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import die, read_json, sha256_file, write_json  # noqa: E402

CONTRACTS = (
    "top_variants.json",
    "structural_metrics.json",
    "manifest_structures.json",
    "raw_mutations.json",
    "mutation_stats.json",
    "docking/vina_affinities.json",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Construye el árbol de salida de la corrida en el workdir"
    )
    parser.add_argument("--source",   required=True, help="directorio stage/data de BUILD_JSONS")
    parser.add_argument("--outdir",   required=True, help="workdir de salida (por defecto '.')")
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--commit",   default="desconocido")
    parser.add_argument("--params",   required=True, help="params.json")
    parser.add_argument("--images",   help="images.json")
    args = parser.parse_args()

    source  = Path(args.source)
    workdir = Path(args.outdir)

    if not source.is_dir():
        die(f"no existe el árbol de la corrida: {source}")

    missing = [name for name in CONTRACTS if not (source / name).is_file()]
    if missing:
        die(f"faltan contratos en {source}: {', '.join(missing)}")

    params = read_json(args.params)
    if not isinstance(params, dict):
        die("--params debe contener un objeto JSON")
    images = read_json(args.images) if args.images else {}

    # Checksums de todos los archivos del contrato
    files: dict[str, str] = {}
    for path in sorted(source.rglob("*")):
        if path.is_file():
            files[path.relative_to(source).as_posix()] = sha256_file(path)

    manifest = {
        "run_name":     args.run_name,
        "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit":   args.commit,
        "params":       params,
        "images":       images,
        "files":        files,
        "contracts":    list(CONTRACTS),
    }

    # ── Construir data/ en el workdir (será copiado por publishDir) ──────────
    data_out = workdir / "data"
    if data_out.exists():
        shutil.rmtree(data_out)
    shutil.copytree(source, data_out)

    # ── Escribir run_manifest.json en el workdir ─────────────────────────────
    write_json(str(workdir / "run_manifest.json"), manifest, sort_keys=True)

    print(f"OK preparado {args.run_name}: {len(files)} archivos en {data_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
