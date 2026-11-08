#!/usr/bin/env python3
"""Pruebas del validador del Contrato de Datos V3 (consumidor).

Uso:
    python -m pytest tests/test_validate_contract.py -q
    python tests/test_validate_contract.py  # sin pytest
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "tests" / "reference" / "tcga_hispanic_v3"
CURATED = ROOT / "tests" / "reference" / "tcga_hispanic_v3_curated_smoke"
sys.path.insert(0, str(ROOT / "bin"))

from validate_contract import (  # noqa: E402
    load_contract,
    summarize,
    validate_contract_dir,
)


def _copy_bundle(destination: Path) -> Path:
    shutil.copytree(REFERENCE, destination)
    return destination


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


def test_bundle_real_valido():
    assert validate_contract_dir(REFERENCE) == []
    summary = summarize(REFERENCE)
    assert summary["contract_version"] == "2.0.0"
    assert summary["bundle_id"].startswith("TCGA-BRCA-HISPANIC__GDC-46.0")
    assert summary["gdc_data_release"].startswith("Data Release 46.0")
    assert summary["mutation_scope"] == "target_panel"
    assert summary["data_origin"] == "gdc_open_access"
    assert summary["curated"] is False
    assert summary["cohort_cases"] == 39
    assert summary["mutation_records"] == 23
    assert summary["mutation_patients"] == 13
    assert summary["clinical_records"] == 234


def test_fixture_curado_no_es_valido():
    errors = validate_contract_dir(CURATED)
    assert errors
    assert any("contract_version incompatible" in error for error in errors)
    assert any("sample_id no tumoral" in error for error in errors)


def test_hash_alterado_se_detecta():
    with tempfile.TemporaryDirectory() as tmp:
        bundle = _copy_bundle(Path(tmp) / "bundle")
        path = bundle / "somatic_mutations.json"
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        errors = validate_contract_dir(bundle)
        assert any("SHA-256 no coincide" in error for error in errors)


def test_bundle_curado_requiere_flag():
    with tempfile.TemporaryDirectory() as tmp:
        bundle = _copy_bundle(Path(tmp) / "bundle")
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["curated"] = True
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        errors = validate_contract_dir(bundle)
        assert any("bundle curado" in error for error in errors)
        assert validate_contract_dir(bundle, allow_curated=True) == []


def test_version_mayor_incorrecta():
    with tempfile.TemporaryDirectory() as tmp:
        bundle = _copy_bundle(Path(tmp) / "bundle")
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["contract_version"] = "3.0.0"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        errors = validate_contract_dir(bundle)
        assert any("contract_version incompatible" in error for error in errors)


def test_muestra_normal_se_rechaza():
    with tempfile.TemporaryDirectory() as tmp:
        bundle = _copy_bundle(Path(tmp) / "bundle")
        path = bundle / "somatic_mutations.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data[0]["sample_id"] = data[0]["sample_id"][:13] + "10A"
        data[0]["sample_ids"] = [data[0]["sample_id"]]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        _rewrite_file(bundle, "somatic_mutations.json")
        errors = validate_contract_dir(bundle)
        assert any("sample_id no tumoral" in error for error in errors)


def test_paciente_fuera_de_cohorte():
    with tempfile.TemporaryDirectory() as tmp:
        bundle = _copy_bundle(Path(tmp) / "bundle")
        path = bundle / "somatic_mutations.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data[0]["patient_id"] = "TCGA-ZZ-ZZZZ"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        _rewrite_file(bundle, "somatic_mutations.json")
        errors = validate_contract_dir(bundle)
        assert any("patient_id fuera de cohorte" in error for error in errors)


def test_load_contract_retorna_payloads():
    contract = load_contract(REFERENCE)
    assert len(contract["cohort_cases.json"]) == 39
    assert len(contract["somatic_mutations.json"]) == 23
    assert len(contract["clinical_attributes.json"]) == 234


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
