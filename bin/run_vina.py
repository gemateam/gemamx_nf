#!/usr/bin/env python3
"""RUN_VINA — un par receptor × fármaco, con semilla fija.

Requisitos del proyecto:
  - una unidad de trabajo por invocación;
  - `--seed` explícita (reproducibilidad) y `--cpu 1`;
  - no escribe en MLflow (de eso se encarga LOG_MLFLOW al final);
  - el log y el resumen quedan junto a la pose para BUILD_JSONS.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import die, write_json  # noqa: E402
from parse_vina import parse_log  # noqa: E402


def vina_version(vina: str) -> str:
    try:
        out = subprocess.run([vina, "--version"], capture_output=True, text=True, timeout=60)
        text = (out.stdout or "") + (out.stderr or "")
        return text.strip().splitlines()[0] if text.strip() else "desconocida"
    except Exception:  # noqa: BLE001
        return "desconocida"


def main() -> int:
    parser = argparse.ArgumentParser(description="Ejecuta AutoDock Vina para un par receptor-ligando")
    parser.add_argument("--receptor", required=True)
    parser.add_argument("--ligand", required=True)
    parser.add_argument("--out", required=True, help="poses PDBQT de salida")
    parser.add_argument("--log", required=True, help="log de texto de Vina")
    parser.add_argument("--summary", required=True, help="JSON con el resultado del docking")
    parser.add_argument("--center", nargs=3, type=float, required=True, metavar=("X", "Y", "Z"))
    parser.add_argument("--box-size", type=float, default=25.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--exhaustiveness", type=int, default=8)
    parser.add_argument("--num-modes", type=int, default=5)
    parser.add_argument("--cpu", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--vina", default="vina", help="ejecutable de Vina")
    parser.add_argument("--variant", help="clave de variante (p. ej. PIK3CA_H1047R)")
    parser.add_argument("--drug", help="nombre del fármaco")
    args = parser.parse_args()

    for label, path in (("receptor", args.receptor), ("ligando", args.ligand)):
        if not Path(path).exists():
            die(f"no existe el {label}: {path}")
    if args.seed < 0:
        die(f"--seed debe ser >= 0, recibido {args.seed}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    log = Path(args.log)
    log.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        args.vina,
        "--receptor", str(args.receptor),
        "--ligand", str(args.ligand),
        "--center_x", f"{args.center[0]:.3f}",
        "--center_y", f"{args.center[1]:.3f}",
        "--center_z", f"{args.center[2]:.3f}",
        "--size_x", f"{args.box_size:g}",
        "--size_y", f"{args.box_size:g}",
        "--size_z", f"{args.box_size:g}",
        "--exhaustiveness", str(args.exhaustiveness),
        "--num_modes", str(args.num_modes),
        "--seed", str(args.seed),
        "--cpu", str(args.cpu),
        "--out", str(out),
    ]

    started = time.monotonic()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout)
    except FileNotFoundError:
        die(f"no se encontró el ejecutable de Vina: {args.vina}")
    except subprocess.TimeoutExpired:
        die(f"Vina excedió {args.timeout} s para {Path(args.ligand).name} vs {Path(args.receptor).name}")
    elapsed = round(time.monotonic() - started, 1)

    log.write_text((result.stdout or "") + (result.stderr or ""), encoding="utf-8", newline="\n")

    if result.returncode != 0:
        tail = " | ".join((result.stderr or result.stdout or "").strip().splitlines()[-3:])
        die(f"Vina terminó con código {result.returncode}: {tail}")
    if not out.exists() or out.stat().st_size < 200:
        die(f"Vina no generó poses válidas en {out}")

    try:
        parsed = parse_log(log)
    except FileNotFoundError:
        die(f"no se generó el log de Vina: {log}")
    if parsed["best_affinity"] is None:
        die(f"el log de Vina no contiene afinidades: {log}")

    summary = {
        "variant": args.variant or Path(args.receptor).stem,
        "drug": args.drug or Path(args.ligand).stem,
        "receptor": Path(args.receptor).name,
        "ligand": Path(args.ligand).name,
        "out_pdbqt": out.name,
        "log": log.name,
        "center": [round(c, 3) for c in args.center],
        "box_size": args.box_size,
        "seed": args.seed,
        "exhaustiveness": args.exhaustiveness,
        "num_modes_requested": args.num_modes,
        "cpu": args.cpu,
        "best_affinity": parsed["best_affinity"],
        "modes": parsed["modes"],
        "vina_version": vina_version(args.vina),
        "elapsed_sec": elapsed,
    }
    write_json(args.summary, summary, sort_keys=True)
    print(f"OK {Path(args.receptor).stem} vs {Path(args.ligand).stem}: "
          f"{parsed['best_affinity']} kcal/mol ({len(parsed['modes'])} poses)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
