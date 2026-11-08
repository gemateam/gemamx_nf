#!/usr/bin/env python3
"""Pruebas de la ingesta del Contrato de Datos V3 en el consumidor.

Ejercita `bin/ingest_cbioportal.py --contract-dir` de extremo a extremo con el
bundle real de `tests/reference/tcga_hispanic_v3` (sin red) y comprueba:

  - una fila por `(patient_id, variant_id)` y muestra tumoral;
  - ranking por paciente, no por muestra;
  - clínica a nivel paciente (39 pacientes) con procedencia del contrato;
  - `contract_provenance.json` con release, bundle y alcance;
  - rechazo de bundles manipulados (hash o muestra no tumoral).

Uso:
    python -m pytest tests/test_v3_contract_ingest.py -q
    python tests/test_v3_contract_ingest.py  # sin pytest
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
REFERENCE = ROOT / "tests" / "reference" / "tcga_hispanic_v3"
GENES = "PIK3CA,TP53,AKT1,CDH1,PTEN,ESR1,GATA3,MAP3K1,ERBB2,BRCA1,BRCA2"
TUMOR_RE = re.compile(r"^TCGA-[A-Z0-9]{2}-[A-Z0-9]{4}-0[1-9][A-Z]?$")
BUNDLE_ID = "TCGA-BRCA-HISPANIC__GDC-46.0__20261108T025940Z__de39c9eb"
RELEASE = "Data Release 46.0 - August 10, 2026"


def run_ingest(contract_dir: Path, outdir: Path, extra: list[str] | None = None):
    command = [
        sys.executable, str(BIN / "ingest_cbioportal.py"),
        "--contract-dir", str(contract_dir),
        "--genes", GENES,
        "--max-variants", "30",
        "--outdir", str(outdir),
        *(extra or []),
    ]
    return subprocess.run(command, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _rewrite_file(bundle: Path, name: str) -> None:
    """Recalcula hash/bytes/records en el manifiesto tras editar un JSON."""
    path = bundle / name
    data = json.loads(path.read_text(encoding="utf-8"))
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw = path.read_bytes()
    manifest["files"][name] = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "records": len(data),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")


def _ingest_ok(tmp: Path) -> tuple[Path, dict]:
    outdir = tmp / "out"
    result = run_ingest(REFERENCE, outdir)
    assert result.returncode == 0, result.stderr
    stats_result = subprocess.run([
        sys.executable, str(BIN / "build_stats.py"),
        "--raw", str(outdir / "raw_mutations.json"),
        "--out", str(outdir / "mutation_stats.json"),
        "--contract-dir", str(REFERENCE),
        "--total-samples", "13",
    ], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert stats_result.returncode == 0, stats_result.stderr
    payloads = {
        "raw": load(outdir / "raw_mutations.json"),
        "top": load(outdir / "top_variants.json"),
        "stats": load(outdir / "mutation_stats.json"),
        "clinical": load(outdir / "clinical_metadata.json"),
        "summary": load(outdir / "variant_clinical_summary.json"),
        "provenance": load(outdir / "contract_provenance.json"),
        "ingestion": load(outdir / "data_ingest.json"),
        "ingestion": load(outdir / "data_ingest.json"),
    }
    return outdir, payloads


def test_ingesta_contrato_real():
    with tempfile.TemporaryDirectory() as tmp:
        outdir, data = _ingest_ok(Path(tmp))

        # Mutaciones: 23 registros, una fila por (patient, variant)
        raw = data["raw"]
        assert len(raw) == 23
        keys = {(row["patient_id"], row["variant_id"]) for row in raw}
        assert len(keys) == 23, "clave (patient_id, variant_id) no es única"
        assert all(re.match(r"^[0-9a-f]{16}$", row["variant_id"]) for row in raw)
        # El identificador sigue la fórmula documentada en el contrato 2.0.0.
        for row in raw:
            key = "|".join([
                row["patient_id"], row["hugo_symbol"], row["protein_change"],
                row["chromosome"], str(row["start_position"]),
                row.get("reference_allele") or "",
                row.get("tumor_seq_allele2") or "",
            ])
            expected = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
            assert row["variant_id"] == expected, key

        # Todas las muestras son tumorales (01-09) y con paciente de 12 chars
        for row in raw:
            assert TUMOR_RE.match(row["sample_id"]), row["sample_id"]
            assert len(row["patient_id"]) == 12, row["patient_id"]
            assert all(TUMOR_RE.match(extra) for extra in row["sample_ids"])

        # Estadísticas: el tamaño viene del manifiesto ETL, no del parámetro legacy.
        stats = data["stats"]
        assert stats["total_samples"] == 39
        assert stats["cohort_unit"] == "patient"
        assert stats["cohort_units_with_mutations"] == 13
        assert stats["cohort_units_without_mutations"] == 26
        assert stats["total_mutations"] == 23

        # Ranking: 21 variantes distintas, contadas por paciente
        top = data["top"]
        assert len(top) == 21
        frequencies = {(row["hugo_symbol"], row["protein_change"]): row["frequency"]
                       for row in top}
        assert frequencies[("PIK3CA", "E542K")] == 2
        assert frequencies[("PIK3CA", "H1047R")] == 2
        assert frequencies[("GATA3", "M293K")] == 1
        assert ("GATA3", "M294K") not in frequencies
        assert frequencies[("BRCA2", "E1158Q")] == 1
        assert frequencies[("BRCA2", "K1191N")] == 1

        # Clínica: un registro por paciente de la cohorte (39)
        clinical = data["clinical"]
        assert len(clinical) == 39
        assert all(row["cohort_unit"] == "patient" for row in clinical)
        assert all(row["sample_id"] == row["patient_id"] for row in clinical)
        assert all(row["ethnicity"] == "HISPANIC OR LATINO" for row in clinical)
        assert all(row["race_source"] in (None, "GDC:demographics")
                   for row in clinical)
        assert all(row["bundle_id"] == BUNDLE_ID for row in clinical)

        # Agregados variante x clínica y celdas pequeñas marcadas
        summary = data["summary"]
        assert len(summary) == 21
        assert all("small_cells" in row for row in summary)
        assert all(row["small_cell_threshold"] == 5 for row in summary)
        pik3ca = next(row for row in summary
                      if row["hugo_symbol"] == "PIK3CA"
                      and row["protein_change"] == "E542K")
        assert pik3ca["sample_count"] == 2
        assert pik3ca["bundle_id"] == BUNDLE_ID

        # Procedencia publicada para webapp/MLflow
        provenance = data["provenance"]
        assert provenance["contract_version"] == "2.0.0"
        assert provenance["bundle_id"] == BUNDLE_ID
        assert provenance["gdc_data_release"] == RELEASE
        assert provenance["mutation_scope"] == "target_panel"
        assert provenance["data_origin"] == "gdc_open_access"
        assert provenance["curated"] is False
        assert provenance["cohort_total_cases"] == 39
        assert provenance["mutation_records"] == 23
        assert provenance["clinical_records"] == 234
        assert (outdir / "contract_provenance.json").is_file()

        ingestion = data["ingestion"]
        assert ingestion["mode"] == "etl_contract"
        assert ingestion["query"]["cohort_filter"] == "project_id = TCGA-BRCA AND ethnicity = HISPANIC OR LATINO"
        assert ingestion["query"]["bundle"]["bundle_id"] == BUNDLE_ID
        assert ingestion["counts"]["raw_mutation_records"] == 23

        ingestion = data["ingestion"]
        assert ingestion["mode"] == "etl_contract"
        assert ingestion["query"]["cohort_filter"] == "project_id = TCGA-BRCA AND ethnicity = HISPANIC OR LATINO"
        assert ingestion["query"]["bundle"]["bundle_id"] == BUNDLE_ID
        assert ingestion["counts"]["raw_mutation_records"] == 23


def test_bundle_manipulado_falla():
    with tempfile.TemporaryDirectory() as tmp:
        bundle = Path(tmp) / "bundle"
        shutil.copytree(REFERENCE, bundle)

        # 1. Hash alterado: el validador debe abortar antes de ingerir.
        path = bundle / "somatic_mutations.json"
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        result = run_ingest(bundle, Path(tmp) / "out-hash")
        assert result.returncode != 0
        assert "SHA-256" in result.stderr

        # 2. Muestra normal con manifiesto recalculado: también debe fallar.
        bundle2 = Path(tmp) / "bundle2"
        shutil.copytree(REFERENCE, bundle2)
        path = bundle2 / "somatic_mutations.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data[0]["sample_id"] = data[0]["sample_id"][:13] + "10A"
        data[0]["sample_ids"] = [data[0]["sample_id"]]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        _rewrite_file(bundle2, "somatic_mutations.json")
        result = run_ingest(bundle2, Path(tmp) / "out-normal")
        assert result.returncode != 0
        assert "no tumoral" in result.stderr


def test_fixture_curado_falla_sin_flag():
    with tempfile.TemporaryDirectory() as tmp:
        curated = ROOT / "tests" / "reference" / "tcga_hispanic_v3_curated_smoke"
        result = run_ingest(curated, Path(tmp) / "out")
        assert result.returncode != 0
        assert "contract_version incompatible" in result.stderr


def test_main_v3_sends_contract_provenance_to_mlflow():
    workflow = (ROOT / "main_v3.nf").read_text(encoding="utf-8")
    mlflow_call = workflow.split("LOG_MLFLOW(", 1)[1].split("\n    )", 1)[0]
    assert ".mix(BUILD_JSONS.out.contract_provenance_out)" in mlflow_call
    assert ".mix(BUILD_JSONS.out.data_ingest_out)" in mlflow_call
    assert "INGEST.out.ingest_metadata" in workflow


def main() -> int:
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"  OK  {test.__name__}")
    print(f"\n{len(tests)} pruebas OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
