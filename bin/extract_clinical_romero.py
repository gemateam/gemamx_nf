#!/usr/bin/env python3
"""EXTRACT_CLINICAL_ROMERO — M5a del pipeline V2.

Extrae metadatos clínicos del suplementario MOESM4 de Romero-Córdoba 2021
(hoja 'Features': edad, subtipo IHC, PAM50, grado SBR, histología, etc.).

Entrada:
  --source   41467_2021_22478_MOESM4_ESM.xlsx

Salida en --outdir:
  clinical_metadata.json

El lector de hojas es el de INGEST_ROMERO (bin/ingest_romero.py), no una copia:
coloca cada celda por su referencia `r`, de modo que una celda omitida no
desplaza el resto de la fila, y acepta cadenas en línea. Los marcadores de celda
vacía ("-", ".", "NA", "N/A", "—") se normalizan con `cell_text()` y aquí se
convierten además en `null` de JSON. El cero se conserva: `0` embarazos es un
dato, no un valor ausente.

Derivado del script original v2/scripts/extract_clinical_romero.py;
refactorizado para aceptar rutas por argumento.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Una sola implementación de las reglas de vacíos y de alineación de columnas:
# ver tests/test_xlsx_parser.py.
from ingest_romero import (  # noqa: E402
    cell_text,
    load_xlsx_sheet_rows,  # noqa: F401  (reexportado: misma API que antes)
    sheet_to_dicts,
)


def clean(v: object) -> str | None:
    """Texto limpio de una celda; `None` si está vacía o es marcador de vacío.

    No se usa `v or ""`, que descartaría el cero: `Number of pregnancies = 0`
    es un dato, no un valor ausente.
    """
    return cell_text(v) or None


def parse_int(v: object) -> int | None:
    t = clean(v)
    if t is None:
        return None
    try:
        return int(float(t))
    except Exception:
        return None


def normalize_row(row: dict) -> dict:
    return {
        "sample_id":             clean(row.get("Tumor Sample Barcode")),
        "mutation_wes":          clean(row.get("Mutation WES")),
        "er_ihc":                clean(row.get("ER  (IHC)")),
        "pr_ihc":                clean(row.get("PR (IHC)")),
        "her2_ihc":              clean(row.get("Her2 (IHC)")),
        "class_ihc":             clean(row.get("Class IHC")),
        "ihc_subtype":           clean(row.get("IHC subtype")),
        "pam50":                 clean(row.get("Pam50")),
        "age":                   parse_int(row.get("Age")),
        "age_class":             clean(row.get("Age class")),
        "histology":             clean(row.get("Histology")),
        "grade_sbr":             clean(row.get("Grade (SBR)")),
        "tumor_size_mm":         parse_int(row.get("Tumor Size (mm) ")),
        "tnm":                   clean(row.get("TNM")),
        "age_at_menarche":       parse_int(row.get("Age at menarche")),
        "number_of_pregnancies": parse_int(row.get("Number of pregnancies")),
        "menopause":             clean(row.get("Menopause")),
        "age_at_menopause":      parse_int(row.get("Age at menopuse")),
        "source_dataset":        "Romero-Cordoba 2021 HM",
        "source_center":         "FUCAM / HM cohort",
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Extrae metadatos clínicos del suplementario Romero MOESM4")
    ap.add_argument("--source", required=True,
                    help="41467_2021_22478_MOESM4_ESM.xlsx")
    ap.add_argument("--outdir", required=True,
                    help="directorio de salida")
    args = ap.parse_args()

    source = Path(args.source)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    rows  = sheet_to_dicts(source, "Features", header_row=3,
                           required=("Tumor Sample Barcode", "Age", "Pam50"))
    items = []
    for row in rows:
        record = normalize_row(row)
        if record["sample_id"]:
            items.append(record)

    (outdir / "clinical_metadata.json").write_text(
        json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"OK metadatos clínicos Romero: {len(items)} registros")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
