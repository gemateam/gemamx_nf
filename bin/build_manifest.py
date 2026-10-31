#!/usr/bin/env python3
"""BUILD_MANIFEST — indexa estructuras en un manifest {clave: ruta}.

Claves: `<GEN>_WT` y `<GEN>_<CAMBIO>`. Se descartan archivos dummy del legado
(HEADER DUMMY, placeholder, *_MUT) y los que pesan menos de --min-bytes.
Las rutas se escriben relativas al directorio de estructuras con el prefijo
que consume la app (`data/structures/...`), nunca rutas absolutas.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import die, write_json  # noqa: E402

SUFFIXES = {".pdb": 2, ".cif": 1, ".mmcif": 1}
SKIP_MARKERS = ("placeholder", "_mut", "dummy")


def key_for(path: Path) -> str:
    stem = path.stem
    if stem.endswith("_model_0"):
        stem = stem[:-len("_model_0")]
    return stem


def is_dummy(path: Path, min_bytes: int) -> bool:
    if path.stat().st_size < min_bytes:
        return True
    lowered = path.name.lower()
    if any(marker in lowered for marker in SKIP_MARKERS if marker != "_mut"):
        return True
    try:
        head = path.read_bytes()[:200].decode("ascii", errors="ignore").upper()
    except OSError:
        return True
    return "DUMMY" in head


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera manifest_structures.json")
    parser.add_argument("--structures-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--prefix", default="data/structures")
    parser.add_argument("--min-bytes", type=int, default=1000)
    args = parser.parse_args()

    root = Path(args.structures_dir)
    if not root.is_dir():
        die(f"no existe el directorio de estructuras: {root}")

    chosen: dict[str, tuple[int, str]] = {}
    skipped = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUFFIXES:
            continue
        if is_dummy(path, args.min_bytes):
            skipped += 1
            continue
        key = key_for(path)
        if not key:
            skipped += 1
            continue
        priority = SUFFIXES[path.suffix.lower()]
        relpath = path.relative_to(root).as_posix()
        current = chosen.get(key)
        if current is None or priority > current[0]:
            chosen[key] = (priority, relpath)

    if not chosen:
        die(f"no se encontraron estructuras utilizables en {root}")

    manifest = {
        key: f"{args.prefix.rstrip('/')}/{relpath}"
        for key, (_, relpath) in sorted(chosen.items())
    }
    write_json(args.out, manifest, sort_keys=True)
    print(f"OK manifest: {len(manifest)} estructuras ({skipped} descartadas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
