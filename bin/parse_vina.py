#!/usr/bin/env python3
"""Parser de logs de AutoDock Vina (1.1.x y 1.2.x).

Uso como CLI:
    parse_vina.py --log resultados.txt [--out parse.json]

Uso como módulo (lo reutiliza run_vina.py):
    from parse_vina import parse_log
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TABLE_ROW = re.compile(
    r"^\s*(\d+)\s+([-+]?\d+(?:\.\d+)?)\s+([-+]?\d+(?:\.\d+)?)\s+([-+]?\d+(?:\.\d+)?)\s*$"
)
FREE_ENERGY = re.compile(
    r"Estimated Free Energy of Binding\s*:\s*([-+]?\d+(?:\.\d+)?)"
)


def parse_log(path: str | Path) -> dict:
    """Devuelve {'modes': [...], 'best_affinity': float|None, 'source': ...}."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    text = path.read_text(encoding="utf-8", errors="ignore")
    modes = []
    for line in text.splitlines():
        match = TABLE_ROW.match(line)
        if not match:
            continue
        mode = int(match.group(1))
        # Solo filas de la tabla: el modo empieza en 1 y no hay duplicados.
        if mode != len(modes) + 1:
            continue
        modes.append({
            "mode": mode,
            "affinity": float(match.group(2)),
            "rmsd_lb": float(match.group(3)),
            "rmsd_ub": float(match.group(4)),
        })

    best = modes[0]["affinity"] if modes else None
    if best is None:
        fallback = FREE_ENERGY.search(text)
        if fallback:
            best = float(fallback.group(1))

    return {
        "source": path.name,
        "modes": modes,
        "best_affinity": best,
        "table_found": bool(modes),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Parsea un log de AutoDock Vina")
    parser.add_argument("--log", required=True)
    parser.add_argument("--out", help="JSON de salida (si se omite, imprime)")
    args = parser.parse_args()

    try:
        result = parse_log(args.log)
    except FileNotFoundError:
        print(f"ERROR: no existe el log: {args.log}", file=sys.stderr)
        return 1

    if result["best_affinity"] is None:
        print(f"ERROR: no se encontró afinidad en {args.log}", file=sys.stderr)
        return 1

    text = json.dumps(result, indent=4, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
