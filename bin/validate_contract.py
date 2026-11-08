#!/usr/bin/env python3
"""Valida un bundle del Contrato de Datos V3 (TCGA-BRCA Hispano/Latino).

Verifica, sin dependencias externas:

  - versión mayor del contrato (2.x);
  - integridad de los archivos declarados en `manifest.json` (SHA-256, bytes,
    número de registros);
  - que el bundle sea científico (`curated=false`, `data_origin=gdc_open_access`,
    `validation.passed=true`);
  - integridad referencial paciente → mutación / clínica;
  - unicidad de `(patient_id, variant_id)` y de las claves clínicas;
  - que todas las muestras de mutación sean tumorales (`01`–`09`);
  - formato de cromosoma, cambio proteico y posición;
  - coherencia del release del GDC y del alcance (`mutation_scope`).

Uso:

    python bin/validate_contract.py --contract-dir tests/reference/tcga_hispanic_v3
    python bin/validate_contract.py --contract-dir <bundle> --allow-curated

El código de salida es 0 si el bundle es válido y 1 si hay errores.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REQUIRED_FILES = (
    "cohort_cases.json",
    "somatic_mutations.json",
    "clinical_attributes.json",
)
REQUIRED_MANIFEST_KEYS = (
    "contract_version",
    "bundle_id",
    "project_id",
    "gdc_data_release",
    "mutation_scope",
    "data_origin",
    "counts",
    "files",
)
VALID_SCOPES = {"target_panel", "all_missense"}
CASE_CODE_RE = re.compile(r"^TCGA-[A-Z0-9]{2}-[A-Z0-9]{4}$")
TUMOR_SAMPLE_RE = re.compile(r"^TCGA-[A-Z0-9]{2}-[A-Z0-9]{4}-0[1-9][A-Z]?$")
CHROMOSOME_RE = re.compile(r"^(?:[1-9]|1[0-9]|2[0-2]|X|Y|MT)$")
PROTEIN_RE = re.compile(r"^[A-Z*]\d+[A-Z*]$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(f"no existe: {path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON inválido en {path}: {exc}") from None


def load_contract(contract_dir: Path) -> dict:
    """Carga manifiesto y payloads de un bundle (sin validarlos)."""
    contract_dir = Path(contract_dir)
    manifest = read_json(contract_dir / "manifest.json")
    payloads = {name: read_json(contract_dir / name) for name in REQUIRED_FILES}
    return {"dir": contract_dir, "manifest": manifest, **payloads}


def _major(version: str) -> int | None:
    match = re.match(r"^(\d+)\.", str(version or ""))
    return int(match.group(1)) if match else None


def validate_contract_dir(contract_dir: Path, allow_curated: bool = False) -> list[str]:
    """Devuelve la lista de errores del bundle (vacía si es válido)."""
    contract_dir = Path(contract_dir)
    errors: list[str] = []

    if not contract_dir.is_dir():
        return [f"no existe el directorio del contrato: {contract_dir}"]

    try:
        contract = load_contract(contract_dir)
    except (FileNotFoundError, ValueError) as exc:
        return [str(exc)]

    manifest = contract["manifest"]
    if not isinstance(manifest, dict):
        return ["manifest.json debe ser un objeto JSON"]

    for key in REQUIRED_MANIFEST_KEYS:
        if key not in manifest or manifest[key] in (None, "", {}, []):
            errors.append(f"manifest.json sin el campo obligatorio: {key}")

    version = str(manifest.get("contract_version", ""))
    major = _major(version)
    if major != 2:
        errors.append(f"contract_version incompatible: {version!r} (se espera 2.x)")

    if manifest.get("project_id") != "TCGA-BRCA":
        errors.append(f"project_id inesperado: {manifest.get('project_id')!r}")

    scope = manifest.get("mutation_scope")
    if scope not in VALID_SCOPES:
        errors.append(f"mutation_scope inválido: {scope!r}")

    curated = bool(manifest.get("curated"))
    if curated and not allow_curated:
        errors.append("bundle curado: no apto para uso científico (usa --allow-curated solo para smoke)")

    origin = manifest.get("data_origin")
    if not allow_curated and origin != "gdc_open_access":
        errors.append(f"data_origin debe ser 'gdc_open_access', no {origin!r}")

    validation = manifest.get("validation") or {}
    if not allow_curated and validation.get("passed") is not True:
        errors.append("validation.passed no es true")

    release = manifest.get("gdc_data_release")
    if not release:
        errors.append("gdc_data_release vacío")

    # ---------------------------------------------------------------- archivos
    files = manifest.get("files") or {}
    payloads: dict[str, list] = {}
    for name in REQUIRED_FILES:
        info = files.get(name)
        path = contract_dir / name
        if not isinstance(info, dict):
            errors.append(f"manifest.files sin entrada para {name}")
            continue
        if not path.is_file():
            errors.append(f"falta el archivo {name}")
            continue
        actual = sha256_file(path)
        if actual != info.get("sha256"):
            errors.append(f"SHA-256 no coincide para {name}")
        if "bytes" in info and path.stat().st_size != info.get("bytes"):
            errors.append(f"tamaño no coincide para {name}")
        data = contract.get(name)
        if not isinstance(data, list):
            errors.append(f"{name} debe ser una lista JSON")
            continue
        if "records" in info and len(data) != info.get("records"):
            errors.append(
                f"registros no coinciden para {name}: "
                f"{len(data)} != {info.get('records')}"
            )
        payloads[name] = data

    cohort = payloads.get("cohort_cases.json", [])
    mutations = payloads.get("somatic_mutations.json", [])
    clinical = payloads.get("clinical_attributes.json", [])

    counts = manifest.get("counts") or {}
    expected = {
        "cohort_cases": len(cohort),
        "mutation_records": len(mutations),
        "clinical_records": len(clinical),
    }
    for key, actual in expected.items():
        if key in counts and counts.get(key) != actual:
            errors.append(f"counts.{key} no coincide: {counts.get(key)} != {actual}")

    cohort_meta = manifest.get("cohort") or {}
    if "total_cases" in cohort_meta and cohort_meta.get("total_cases") != len(cohort):
        errors.append("cohort.total_cases no coincide con cohort_cases.json")

    # ---------------------------------------------------------------- cohorte
    case_codes: set[str] = set()
    for row in cohort:
        code = row.get("case_code")
        if not isinstance(code, str) or not CASE_CODE_RE.match(code):
            errors.append(f"case_code inválido: {code!r}")
            continue
        if code in case_codes:
            errors.append(f"case_code duplicado: {code}")
        case_codes.add(code)
        if row.get("project_id") != "TCGA-BRCA":
            errors.append(f"cohorte con project_id inesperado: {row.get('project_id')!r}")
        if str(row.get("ethnicity", "")).upper() != "HISPANIC OR LATINO":
            errors.append(f"etnia fuera de cohorte: {code} ({row.get('ethnicity')!r})")
        if row.get("gdc_data_release") and row.get("gdc_data_release") != release:
            errors.append(f"release inconsistente en cohorte: {code}")

    # ---------------------------------------------------------------- clínica
    clinical_keys: set[tuple[str, str, str]] = set()
    for row in clinical:
        patient = row.get("patientId")
        if patient not in case_codes:
            errors.append(f"clinical patientId fuera de cohorte: {patient!r}")
        key = (
            str(row.get("studyId", "")),
            str(patient),
            str(row.get("clinicalAttributeId", "")),
        )
        if key in clinical_keys:
            errors.append(f"clave clínica duplicada: {key}")
        clinical_keys.add(key)
        if row.get("gdc_data_release") and row.get("gdc_data_release") != release:
            errors.append(f"release inconsistente en clínica: {patient}")

    # ------------------------------------------------------------- mutaciones
    variant_keys: set[tuple[str, str]] = set()
    target_genes = {str(g).upper() for g in (manifest.get("target_genes") or [])}
    for row in mutations:
        patient = row.get("patient_id")
        variant = row.get("variant_id")
        if patient not in case_codes:
            errors.append(f"mutation patient_id fuera de cohorte: {patient!r}")
        if not variant:
            errors.append(f"mutación sin variant_id: {patient!r}")
        key = (str(patient), str(variant))
        if key in variant_keys:
            errors.append(f"variante duplicada para paciente: {key}")
        variant_keys.add(key)

        sample_id = row.get("sample_id")
        if not isinstance(sample_id, str) or not TUMOR_SAMPLE_RE.match(sample_id):
            errors.append(
                f"sample_id no tumoral o inválido: {sample_id!r} "
                f"({patient} {row.get('hugo_symbol')} {row.get('protein_change')})"
            )
        for extra in row.get("sample_ids") or []:
            if not isinstance(extra, str) or not TUMOR_SAMPLE_RE.match(extra):
                errors.append(f"sample_ids con muestra no tumoral: {extra!r}")

        chromosome = row.get("chromosome")
        if not isinstance(chromosome, str) or not CHROMOSOME_RE.match(chromosome):
            errors.append(f"chromosome inválido: {chromosome!r}")
        protein = row.get("protein_change")
        if not isinstance(protein, str) or not PROTEIN_RE.match(protein):
            errors.append(f"protein_change inválido: {protein!r}")
        start = row.get("start_position")
        if not isinstance(start, int) or start <= 0:
            errors.append(f"start_position inválido: {start!r}")
        if row.get("gdc_data_release") and row.get("gdc_data_release") != release:
            errors.append(
                f"release inconsistente en mutación: "
                f"{patient} {row.get('hugo_symbol')} {protein}"
            )

        if scope == "target_panel":
            gene = str(row.get("hugo_symbol", "")).upper()
            if target_genes and gene not in target_genes:
                errors.append(f"gen fuera del panel: {gene} ({patient})")

    mutation_patients = {row.get("patient_id") for row in mutations}
    if "mutation_patients" in counts and counts.get("mutation_patients") != len(mutation_patients):
        errors.append("counts.mutation_patients no coincide")

    return sorted(set(errors))


def summarize(contract_dir: Path) -> dict:
    """Resumen legible de un bundle (asume que ya pasó la validación)."""
    contract = load_contract(Path(contract_dir))
    manifest = contract["manifest"]
    return {
        "contract_version": manifest.get("contract_version"),
        "bundle_id": manifest.get("bundle_id"),
        "gdc_data_release": manifest.get("gdc_data_release"),
        "gdc_api_tag": manifest.get("gdc_api_tag"),
        "mutation_scope": manifest.get("mutation_scope"),
        "data_origin": manifest.get("data_origin"),
        "curated": manifest.get("curated"),
        "cohort_cases": len(contract["cohort_cases.json"]),
        "mutation_records": len(contract["somatic_mutations.json"]),
        "mutation_patients": len({row.get("patient_id")
                                  for row in contract["somatic_mutations.json"]}),
        "clinical_records": len(contract["clinical_attributes.json"]),
        "validation_passed": (manifest.get("validation") or {}).get("passed"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida un bundle del Contrato de Datos V3 (TCGA-BRCA)")
    parser.add_argument("--contract-dir", required=True,
                        help="directorio con manifest.json y los tres JSON de datos")
    parser.add_argument("--allow-curated", action="store_true",
                        help="permite bundles curados (solo smoke tests)")
    parser.add_argument("--json-out",
                        help="escribe el resumen de validación en este archivo JSON")
    args = parser.parse_args()

    contract_dir = Path(args.contract_dir)
    errors = validate_contract_dir(contract_dir, allow_curated=args.allow_curated)

    summary: dict = {"contract_dir": str(contract_dir), "valid": not errors,
                     "errors": errors}
    if not errors:
        try:
            summary.update(summarize(contract_dir))
        except (FileNotFoundError, ValueError):
            pass

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if errors:
        print(f"ERROR: contrato inválido en {contract_dir} ({len(errors)} errores)",
              file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"OK contrato válido: {summary.get('bundle_id')}")
    print(f"  contract_version: {summary.get('contract_version')}")
    print(f"  gdc_data_release: {summary.get('gdc_data_release')}")
    print(f"  mutation_scope:   {summary.get('mutation_scope')}")
    print(f"  casos:            {summary.get('cohort_cases')}")
    print(f"  mutaciones:       {summary.get('mutation_records')} "
          f"({summary.get('mutation_patients')} portadores)")
    print(f"  clínica:          {summary.get('clinical_records')} registros")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
