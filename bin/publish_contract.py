#!/usr/bin/env python3
"""PUBLISH (host) — archiva la corrida y promueve el contrato vigente.

Nextflow publica el árbol de cada corrida en `<outdir>/runs/<runName>/data` (lo
hace `publishDir` desde el orquestador, así que ve el filesystem del host). Ese
árbol es inmutable: cada corrida escribe el suyo y nunca se reescribe.

Este script corre en el host, desde `workflow.onComplete`, y:

  1. valida que el árbol de la corrida tenga los seis contratos;
  2. construye `<outdir>/data.tmp` con una copia completa;
  3. sustituye `<outdir>/data` por el nuevo árbol (`data` → `data.old`,
     `data.tmp` → `data`, y se borra `data.old`), de modo que la webapp nunca
     vea un árbol a medias: o el anterior completo, o el nuevo completo;
  4. copia `run_manifest.json` a `<outdir>/` y a `<outdir>/data/`, que es donde
     la webapp lo busca;
  5. con `--archive true` conserva `runs/<runName>/` y actualiza
     `runs/index.json`; con `false` (pruebas de humo) lo borra tras promover;
  6. con `--restart-container <nombre>` reinicia el contenedor de la webapp:
     el `rename` deja su bind mount apuntando al árbol anterior hasta el
     reinicio. Un fallo al reiniciar se avisa, pero no invalida la promoción.

Si la validación falla no se toca nada y se sale con código 2; si la promoción
falla se restaura el árbol anterior y se sale con 3. En ambos casos `data/`
sigue sirviendo la corrida anterior.

Uso:
  python3 bin/publish_contract.py --outdir results --run-name romero_v2_1 --archive true
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Los seis contratos que exige PUBLISH (tests/README.md §3).
CONTRACTS = (
    "top_variants.json",
    "structural_metrics.json",
    "manifest_structures.json",
    "raw_mutations.json",
    "mutation_stats.json",
    "docking/vina_affinities.json",
    "data_ingest.json",
)


def log(message: str) -> None:
    print(message, flush=True)


def validate(run_data: Path) -> list[str]:
    """Contratos que faltan en el árbol de la corrida."""
    return [name for name in CONTRACTS if not (run_data / name).is_file()]


def promote(outdir: Path, run_data: Path, manifest: Path | None) -> None:
    """Sustituye <outdir>/data por una copia de run_data.

    El intercambio son dos `rename` dentro del mismo directorio: `data.old`
    guarda el árbol anterior hasta que el nuevo está en su sitio, y se restaura
    si el segundo rename falla. La ventana en la que `data/` no existe dura
    microsegundos, frente a la copia archivo a archivo que había antes.
    """
    tmp = outdir / "data.tmp"
    old = outdir / "data.old"
    data = outdir / "data"

    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(run_data, tmp)

    if manifest is not None and manifest.is_file():
        shutil.copyfile(manifest, tmp / "run_manifest.json")

    if old.exists():
        shutil.rmtree(old)

    had_previous = data.exists()
    if had_previous:
        data.rename(old)
    try:
        tmp.rename(data)
    except OSError:
        if had_previous:
            old.rename(data)
        raise
    if had_previous:
        shutil.rmtree(old, ignore_errors=True)


def restart_container(name: str, timeout: int = 120) -> bool:
    """Reinicia el contenedor de la webapp para refrescar su bind mount de data/.

    El reemplazo de `data/` es un `rename`: el contenedor sigue viendo el inodo
    anterior hasta que se reinicia. Un fallo al reiniciar se avisa pero no
    invalida la promoción (los datos ya están en su sitio).
    """
    try:
        proc = subprocess.run(["docker", "restart", name],
                              capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        log(f"  aviso: docker no está disponible; reinicia '{name}' a mano")
        return False
    except subprocess.TimeoutExpired:
        log(f"  aviso: 'docker restart {name}' superó {timeout}s; reinícialo a mano")
        return False
    if proc.returncode != 0:
        detalle = (proc.stderr or proc.stdout).strip() or f"código {proc.returncode}"
        log(f"  aviso: no se pudo reiniciar '{name}': {detalle}")
        return False
    log(f"  webapp: '{name}' reiniciado; el bind mount de data/ apunta al árbol nuevo")
    return True


def update_index(outdir: Path, run_name: str, manifest: dict) -> None:
    """Añade o reemplaza la entrada de la corrida en runs/index.json."""
    index_path = outdir / "runs" / "index.json"
    index: list[dict] = []
    if index_path.is_file():
        try:
            cargado = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(cargado, list):
                index = [item for item in cargado if isinstance(item, dict)]
        except (json.JSONDecodeError, OSError):
            log(f"  aviso: index.json ilegible, se reescribe ({index_path})")

    entry = {
        "run_name":     run_name,
        "published_at": manifest.get("published_at", ""),
        "git_commit":   str(manifest.get("git_commit", ""))[:7],
        "path":         f"runs/{run_name}/data",
    }
    index = [item for item in index if item.get("run_name") != run_name]
    index.insert(0, entry)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    log(f"  índice: {len(index)} corrida(s)")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Promueve el contrato vigente y archiva la corrida")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--archive", default="true",
                    help="'true' conserva runs/<runName>; 'false' la borra tras promover")
    ap.add_argument("--restart-container", default="",
                    help="contenedor a reiniciar tras promover (vacío = no reiniciar)")
    args = ap.parse_args()

    outdir = Path(args.outdir).resolve()
    run_dir = outdir / "runs" / args.run_name
    run_data = run_dir / "data"
    archive = str(args.archive).strip().lower() in {"1", "true", "yes", "si", "sí"}

    log(f"PUBLISH {args.run_name}: {outdir}")
    if not run_data.is_dir():
        log(f"  ERROR: no existe el árbol de la corrida: {run_data}")
        return 2
    missing = validate(run_data)
    if missing:
        log(f"  ERROR: faltan contratos en {run_data}: {', '.join(missing)}")
        return 2

    manifest_path = run_dir / "run_manifest.json"
    manifest: dict = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log("  aviso: run_manifest.json ilegible, se ignora en el índice")

    try:
        promote(outdir, run_data, manifest_path if manifest_path.is_file() else None)
    except OSError as exc:
        log(f"  ERROR: no se pudo promover el contrato ({exc}); data/ sigue igual")
        return 3

    # Copia del manifest en la raíz del outdir (trazabilidad de la corrida vigente).
    if manifest_path.is_file():
        shutil.copyfile(manifest_path, outdir / "run_manifest.json")

    if archive:
        update_index(outdir, args.run_name, manifest)
        log(f"  archivo: {run_dir}")
    else:
        shutil.rmtree(run_dir, ignore_errors=True)
        log("  archivado desactivado (publish_run_archive=false): no se conserva la corrida")

    restart = args.restart_container.strip()
    if restart:
        restart_container(restart)

    contratos = ", ".join(CONTRACTS)
    log(f"  OK data/ actualizado con: {contratos}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
