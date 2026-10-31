#!/usr/bin/env python3
"""PUBLISH — sella la corrida y promueve el contrato vigente.

1. Verifica que el árbol publicado (`runs/<runName>/data`) tenga los seis JSON.
2. Copia a un directorio temporal y reemplaza `data/` de forma atómica, para
   que la app nunca vea un árbol a medias. Si algo falla, `data/` no se toca.
3. Escribe `run_manifest.json` con parámetros, commit, imágenes y checksums.

No calcula nada científico: es el único paso que puede tocar el contrato que
consume la app.
"""

from __future__ import annotations

import argparse
import json
import os
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
    parser = argparse.ArgumentParser(description="Publica la corrida y actualiza data/")
    parser.add_argument("--source", required=True, help="runs/<runName>/data")
    parser.add_argument("--target", required=True, help="<outdir>/data")
    parser.add_argument("--manifest", required=True, help="runs/<runName>/run_manifest.json")
    parser.add_argument("--params", required=True, help="params.json (dict)")
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--commit", default="desconocido")
    parser.add_argument("--images", help="JSON con las imágenes usadas")
    args = parser.parse_args()

    source = Path(args.source)
    target = Path(args.target)
    if not source.is_dir():
        die(f"no existe el árbol de la corrida: {source}")

    missing = [name for name in CONTRACTS if not (source / name).is_file()]
    if missing:
        die(f"faltan contratos en {source}: {', '.join(missing)}")

    params = read_json(args.params)
    if not isinstance(params, dict):
        die("--params debe contener un objeto JSON")
    images = read_json(args.images) if args.images else {}

    files = {}
    for path in sorted(source.rglob("*")):
        if path.is_file():
            files[path.relative_to(source).as_posix()] = sha256_file(path)

    manifest = {
        "run_name": args.run_name,
        "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": args.commit,
        "params": params,
        "images": images,
        "files": files,
        "contracts": list(CONTRACTS),
    }

    # Reemplazo atómico dentro del mismo filesystem
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f".{target.name}.tmp-{os.getpid()}"
    backup = target.parent / f".{target.name}.old-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(source, tmp)

    try:
        if target.exists():
            os.replace(target, backup)
        os.replace(tmp, target)
    except OSError as exc:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        if backup.exists() and not target.exists():
            os.replace(backup, target)
        die(f"no se pudo promover {source} -> {target}: {exc}")
    else:
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)

    write_json(args.manifest, manifest, sort_keys=True)
    print(f"OK publicado {args.run_name}: {len(files)} archivos en {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
