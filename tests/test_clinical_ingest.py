#!/usr/bin/env python3
"""Pruebas de la ingesta clínica opcional de V1 (bin/ingest_cbioportal.py).

Comprueban:

  - normalización de atributos, etiquetas y edades;
  - cruce paciente -> muestra y atributos de muestra;
  - agregados variante × clínica con muestras únicas y celdas pequeñas marcadas;
  - el flujo completo con snapshots locales (sin red), incluido que sin flags
    no se escriban los JSON clínicos.

Uso: python3 tests/test_clinical_ingest.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "ingest_cbioportal.py"
MUTATIONS = ROOT / "tests" / "reference" / "mutations_snapshot.json"
CLINICAL = ROOT / "tests" / "reference" / "clinical_snapshot.json"
sys.path.insert(0, str(ROOT / "bin"))

import ingest_cbioportal as ingest  # noqa: E402

ok = 0


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    global ok
    ok += 1
    print(f"  OK  {message}")


def make_tmpdir() -> Path:
    candidates = [Path(tempfile.gettempdir()) / "gemamx-clinical-test",
                  ROOT / ".tmp_clinical_test"]
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


def run_ingest(outdir: Path, *extra: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT),
         "--mutations-json", str(MUTATIONS),
         "--genes", "PIK3CA,TP53,AKT1",
         "--max-variants", "10",
         "--outdir", str(outdir),
         *extra],
        cwd=ROOT, env=env, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )


def test_normalization() -> None:
    print("normalización")
    check(ingest.parse_attributes("race, ETHNICITY,age,RACE") ==
          ["RACE", "ETHNICITY", "AGE"], "atributos en mayúsculas, sin duplicados")
    check(ingest.normalize_label("  Not   Hispanic Or Latino ") ==
          "NOT HISPANIC OR LATINO", "etiquetas comparables entre estudios")
    check(ingest.normalize_label("NA") is None, "NA se trata como ausente")
    check(ingest.parse_age("54") == 54, "edad entera")
    check(ingest.parse_age("54.5") == 54.5, "edad decimal")
    check(ingest.parse_age("NA") is None, "edad ausente")
    check(ingest.parse_age("700") is None, "edad fuera de rango descartada")


def sample_metadata() -> list[dict]:
    records = [
        {"patientId": "P1", "clinicalAttributeId": "RACE", "value": "White"},
        {"patientId": "P1", "clinicalAttributeId": "ETHNICITY", "value": "Not Hispanic Or Latino"},
        {"patientId": "P1", "clinicalAttributeId": "AGE", "value": "50"},
        {"patientId": "P2", "sampleId": "S2-01", "clinicalAttributeId": "RACE", "value": "ASIAN"},
    ]
    return ingest.build_clinical_metadata(
        ["S1-01", "S2-01", "S3-01"],
        {"S1-01": "P1", "S2-01": "P2", "S3-01": "P3"},
        records, ["RACE", "ETHNICITY", "AGE"], "test",
    )


def test_metadata() -> None:
    print("clinical_metadata")
    metadata = {row["sample_id"]: row for row in sample_metadata()}
    check(len(metadata) == 3, "un registro por muestra")
    check(metadata["S1-01"]["race"] == "WHITE", "raza normalizada")
    check(metadata["S1-01"]["ethnicity"] == "NOT HISPANIC OR LATINO", "etnia normalizada")
    check(metadata["S1-01"]["age"] == 50, "edad numérica")
    check(metadata["S1-01"]["missing_attributes"] == [], "sin atributos ausentes")
    check(metadata["S1-01"]["mutation_wes"] == "Yes", "marcado como cohorte secuenciada")
    check(metadata["S2-01"]["missing_attributes"] == ["ETHNICITY", "AGE"],
          "atributos ausentes explícitos")
    check(metadata["S2-01"]["ethnicity"] is None, "etnia ausente -> None")
    check(metadata["S3-01"]["missing_attributes"] == ["RACE", "ETHNICITY", "AGE"],
          "muestra sin registros clínicos")


def test_summary() -> None:
    print("variant_clinical_summary")
    top = [{"hugo_symbol": "G", "protein_change": "A1B"}]
    rows = [
        # Dos mutaciones en la misma muestra: sample_count debe contar 1.
        {"hugo_symbol": "G", "protein_change": "A1B", "sample_id": "S1-01"},
        {"hugo_symbol": "G", "protein_change": "A1B", "sample_id": "S1-01"},
        {"hugo_symbol": "G", "protein_change": "A1B", "sample_id": "S2-01"},
        {"hugo_symbol": "G", "protein_change": "A1B", "sample_id": "S3-01"},
        {"hugo_symbol": "G", "protein_change": "OTHER", "sample_id": "S3-01"},
    ]
    summary = ingest.build_variant_clinical_summary(
        top, rows, sample_metadata(), min_cell=5, source="test")
    check(len(summary) == 1, "una entrada por variante priorizada")
    row = summary[0]
    check(row["variant_id"] == "G_A1B", "identificador canónico")
    check(row["sample_count"] == 3, "muestras únicas, no mutaciones")
    check(row["matched_clinical_count"] == 3, "cruce con clinical_metadata")
    check(row["ethnicity_distribution"] == {"Sin dato": 2, "NOT HISPANIC OR LATINO": 1},
          "distribución de etnia con ausentes")
    check(row["race_distribution"] == {"Sin dato": 1, "ASIAN": 1, "WHITE": 1},
          "distribución de raza con ausentes")
    check(row["age"] == {"n": 1, "mean": 50.0, "min": 50, "max": 50}, "resumen de edad")
    check("ethnicity:HISPANIC OR LATINO" not in row["small_cells"],
          "solo se marcan celdas presentes")
    check(set(row["small_cells"]) == {
        "ethnicity:Sin dato", "ethnicity:NOT HISPANIC OR LATINO",
        "race:Sin dato", "race:ASIAN", "race:WHITE",
    }, "todas las celdas < umbral quedan marcadas")
    check(row["small_cell_threshold"] == 5, "umbral registrado")
    check("no son ancestría genética" in row["clinical_data_note"],
          "nota de autorreporte presente")

    relaxed = ingest.build_variant_clinical_summary(
        top, rows, sample_metadata(), min_cell=1, source="test")
    check(relaxed[0]["small_cells"] == [], "umbral 1 no marca celdas")


def test_end_to_end(tmpdir: Path) -> None:
    print("flujo completo con snapshots")
    outdir = tmpdir / "with_clinical"
    result = run_ingest(outdir,
                        "--clinical-json", str(CLINICAL),
                        "--clinical-small-cell", "5")
    check(result.returncode == 0, f"ingesta clínica termina con 0 ({result.stderr[-200:]})")
    metadata = json.loads((outdir / "clinical_metadata.json").read_text(encoding="utf-8"))
    summary = json.loads((outdir / "variant_clinical_summary.json").read_text(encoding="utf-8"))
    check(len(metadata) == 13, "13 muestras en clinical_metadata.json")
    check(len(summary) == 3, "3 variantes en variant_clinical_summary.json")
    by_variant = {row["variant_id"]: row for row in summary}
    pik3ca = by_variant["PIK3CA_H1047R"]
    check(pik3ca["sample_count"] == 5, "PIK3CA_H1047R en 5 muestras")
    check(pik3ca["matched_clinical_count"] == 5, "las 5 cruzan con clínica")
    check(pik3ca["ethnicity_distribution"] == {
        "NOT HISPANIC OR LATINO": 2, "Sin dato": 2, "HISPANIC OR LATINO": 1,
    }, "etnia de PIK3CA_H1047R")
    check("ethnicity:HISPANIC OR LATINO" in pik3ca["small_cells"],
          "subgrupo hispano marcado como celda pequeña")
    check("snapshot" in pik3ca["clinical_source"], "provenance del snapshot")

    plain = tmpdir / "without_clinical"
    result = run_ingest(plain)
    check(result.returncode == 0, "ingesta base sigue funcionando")
    check(not (plain / "clinical_metadata.json").exists(),
          "sin flags no se escribe clinical_metadata.json")
    check(not (plain / "variant_clinical_summary.json").exists(),
          "sin flags no se escribe variant_clinical_summary.json")


def main() -> int:
    print("== ingesta clínica V1 ==")
    test_normalization()
    test_metadata()
    test_summary()
    test_end_to_end(make_tmpdir())
    print(f"\n{ok} comprobaciones OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
