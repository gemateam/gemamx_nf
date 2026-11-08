#!/usr/bin/env python3
"""Prueba de bin/publish_contract.py (archivo por corrida y promoción atómica).

Construye árboles de corrida falsos en un directorio temporal y comprueba:

  - la primera corrida crea data/ y el índice;
  - la segunda sustituye data/ sin dejar restos de la anterior;
  - un árbol incompleto no toca data/ (código 2);
  - --archive false promueve pero no conserva runs/<run> ni toca el índice;
  - repetir la misma corrida no duplica la entrada del índice.

Uso: python3 tests/test_publish_contract.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "publish_contract.py"
sys.path.insert(0, str(ROOT / "bin"))

import publish_contract  # noqa: E402

CONTRACTS = (
    "top_variants.json",
    "structural_metrics.json",
    "manifest_structures.json",
    "raw_mutations.json",
    "mutation_stats.json",
    "docking/vina_affinities.json",
    "data_ingest.json",
)

ok = 0


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    global ok
    ok += 1
    print(f"  OK  {message}")


def make_tmpdir() -> Path:
    candidates = [Path(tempfile.gettempdir()) / "gemamx-publish-test",
                  ROOT / ".tmp_publish_test"]
    for directory in candidates:
        try:
            shutil.rmtree(directory, ignore_errors=True)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / ".probe").write_text("x", encoding="utf-8")
            (directory / ".probe").unlink()
            return directory
        except OSError:
            continue
    raise RuntimeError("no hay ningún directorio temporal escribible")


def make_run(outdir: Path, run_name: str, *, marker: str,
             complete: bool = True) -> Path:
    """Árbol de corrida como el que deja publishDir en runs/<run>/."""
    run_dir = outdir / "runs" / run_name
    data = run_dir / "data"
    data.mkdir(parents=True, exist_ok=True)
    for name in CONTRACTS:
        if not complete and name == "mutation_stats.json":
            continue
        target = data / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"marker": marker}), encoding="utf-8")
    (data / "structures").mkdir(exist_ok=True)
    (data / "structures" / f"{marker}.pdb").write_text("ATOM\n", encoding="utf-8")
    (run_dir / "run_manifest.json").write_text(json.dumps({
        "run_name": run_name,
        "published_at": f"2026-11-04T00:00:0{len(marker)}Z",
        "git_commit": "1234567890abcdef",
        "params": {"study_id": "test"},
    }), encoding="utf-8")
    return data


def run_script(outdir: Path, run_name: str, archive: str = "true",
               restart: str | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT), "--outdir", str(outdir),
           "--run-name", run_name, "--archive", archive]
    if restart is not None:
        cmd += ["--restart-container", restart]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def index(outdir: Path) -> list[dict]:
    path = outdir / "runs" / "index.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def main() -> int:
    tmpdir = make_tmpdir()
    try:
        outdir = tmpdir / "results"

        print("> Primera corrida")
        make_run(outdir, "run_a", marker="a")
        proc = run_script(outdir, "run_a")
        check(proc.returncode == 0, f"la promoción termina con código 0 ({proc.stdout.strip().splitlines()[-1]})")
        check((outdir / "data" / "top_variants.json").is_file(), "data/ contiene los contratos")
        check(json.loads((outdir / "data" / "top_variants.json").read_text())["marker"] == "a",
              "data/ tiene el contenido de run_a")
        check((outdir / "data" / "structures" / "a.pdb").is_file(), "data/ incluye las estructuras")
        check((outdir / "data" / "run_manifest.json").is_file(),
              "run_manifest.json queda dentro de data/ (lo busca la webapp)")
        check((outdir / "run_manifest.json").is_file(), "run_manifest.json queda en la raíz del outdir")
        check((outdir / "runs" / "run_a" / "data").is_dir(), "la corrida se conserva archivada")
        check(len(index(outdir)) == 1 and index(outdir)[0]["run_name"] == "run_a",
              "el índice registra la corrida")
        check(index(outdir)[0]["git_commit"] == "1234567", "el índice acorta el commit")
        check(not (outdir / "data.tmp").exists() and not (outdir / "data.old").exists(),
              "no quedan directorios temporales")

        print("> Segunda corrida: sustituye el contrato sin restos")
        make_run(outdir, "run_b", marker="b")
        proc = run_script(outdir, "run_b")
        check(proc.returncode == 0, "la segunda promoción termina con código 0")
        check(json.loads((outdir / "data" / "top_variants.json").read_text())["marker"] == "b",
              "data/ pasa a run_b")
        check(not (outdir / "data" / "structures" / "a.pdb").exists(),
              "desaparecen las estructuras de la corrida anterior (no se mezclan)")
        check([e["run_name"] for e in index(outdir)] == ["run_b", "run_a"],
              "el índice queda con la más reciente primero")

        print("> Árbol incompleto: no debe tocar data/")
        before = digest(outdir / "data" / "top_variants.json")
        make_run(outdir, "run_roto", marker="c", complete=False)
        proc = run_script(outdir, "run_roto")
        check(proc.returncode == 2, "un árbol sin contratos sale con código 2")
        check("faltan contratos" in proc.stdout, "el error dice qué contrato falta")
        check(digest(outdir / "data" / "top_variants.json") == before,
              "data/ sigue intacto tras el fallo")
        check([e["run_name"] for e in index(outdir)] == ["run_b", "run_a"],
              "el índice no cambia tras el fallo")

        print("> Corrida sin archivar (prueba de humo)")
        make_run(outdir, "run_smoke", marker="d")
        proc = run_script(outdir, "run_smoke", archive="false")
        check(proc.returncode == 0, "--archive false termina con código 0")
        check(json.loads((outdir / "data" / "top_variants.json").read_text())["marker"] == "d",
              "--archive false también promueve data/")
        check(not (outdir / "runs" / "run_smoke").exists(),
              "--archive false no conserva runs/<run>")
        check([e["run_name"] for e in index(outdir)] == ["run_b", "run_a"],
              "--archive false no toca el índice")

        print("> Repetir la misma corrida no duplica el índice")
        make_run(outdir, "run_e", marker="e")
        run_script(outdir, "run_e")
        run_script(outdir, "run_e")
        check([e["run_name"] for e in index(outdir)].count("run_e") == 1,
              "el índice no duplica la corrida repetida")

        print("> Outdir sin data/ previo")
        otro = tmpdir / "otro"
        make_run(otro, "run_x", marker="x")
        proc = run_script(otro, "run_x")
        check(proc.returncode == 0, "la primera promoción no necesita data/ previo")
        check((otro / "data" / "mutation_stats.json").is_file(), "crea data/ desde cero")

        print("> Reinicio de la webapp al promover")
        from unittest import mock

        llamadas: list[list[str]] = []

        def fake_ok(cmd, **kwargs):
            llamadas.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "gemamx_webapp\n", "")

        with mock.patch("subprocess.run", side_effect=fake_ok):
            check(publish_contract.restart_container("gemamx_webapp"),
                  "restart_container devuelve True si docker responde")
        check(llamadas == [["docker", "restart", "gemamx_webapp"]],
              "restart_container ejecuta 'docker restart <contenedor>'")

        def fake_error(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, "", "No such container")

        with mock.patch("subprocess.run", side_effect=fake_error):
            check(not publish_contract.restart_container("fantasma"),
                  "un contenedor inexistente avisa pero no rompe la promoción")

        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            check(not publish_contract.restart_container("gemamx_webapp"),
                  "sin docker en el host solo avisa")

        make_run(outdir, "run_sin_reinicio", marker="s")
        proc = run_script(outdir, "run_sin_reinicio", restart="")
        check(proc.returncode == 0 and "webapp:" not in proc.stdout,
              "--restart-container vacío no reinicia nada")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print(f"OK publish_contract ({ok} comprobaciones)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
