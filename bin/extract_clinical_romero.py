#!/usr/bin/env python3
"""EXTRACT_CLINICAL_ROMERO — M5a del pipeline V2.

Extrae metadatos clínicos del suplementario MOESM4 de Romero-Córdoba 2021
(hoja 'Features': edad, subtipo IHC, PAM50, grado SBR, histología, etc.).

Entrada:
  --source   41467_2021_22478_MOESM4_ESM.xlsx

Salida en --outdir:
  clinical_metadata.json

Derivado del script original v2/scripts/extract_clinical_romero.py;
refactorizado para aceptar rutas por argumento.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel":  "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkg":  "http://schemas.openxmlformats.org/package/2006/relationships",
}


def load_xlsx_sheet_rows(path: Path, sheet_name: str) -> list[list[str]]:
    with zipfile.ZipFile(path) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("main:si", NS):
                text = "".join(t.text or "" for t in si.findall(".//main:t", NS))
                shared.append(text)

        wb  = ET.fromstring(zf.read("xl/workbook.xml"))
        rel = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_map = {r.attrib["Id"]: r.attrib["Target"]
                   for r in rel.findall("pkg:Relationship", NS)}

        target = None
        for sheet in wb.find("main:sheets", NS):
            if sheet.attrib.get("name") == sheet_name:
                rid = sheet.attrib.get(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                target = "xl/" + rel_map[rid]
                break
        if not target:
            raise ValueError(f"Hoja no encontrada: {sheet_name!r}")

        sheet_xml = ET.fromstring(zf.read(target))
        rows: list[list[str]] = []
        for row in sheet_xml.findall(".//main:sheetData/main:row", NS):
            values: list[str] = []
            for cell in row.findall("main:c", NS):
                ctype = cell.attrib.get("t")
                v_el  = cell.find("main:v", NS)
                value = "" if (v_el is None or v_el.text is None) else v_el.text
                if ctype == "s" and value.isdigit():
                    idx   = int(value)
                    value = shared[idx] if idx < len(shared) else value
                values.append(value)
            rows.append(values)
        return rows


def sheet_to_dicts(path: Path, sheet_name: str,
                   header_row_idx: int = 1) -> list[dict[str, str]]:
    rows   = load_xlsx_sheet_rows(path, sheet_name)
    header = rows[header_row_idx]
    width  = len(header)
    result = []
    for row in rows[header_row_idx + 1:]:
        if not any(str(v).strip() for v in row):
            continue
        padded = row + [""] * (width - len(row))
        result.append({str(header[i]).strip(): padded[i] for i in range(width)})
    return result


def clean(v: object) -> str | None:
    t = str(v or "").strip()
    return None if not t or t.upper() == "NA" else t


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

    rows  = sheet_to_dicts(source, "Features", header_row_idx=1)
    items = [normalize_row(r) for r in rows if normalize_row(r).get("sample_id")]

    (outdir / "clinical_metadata.json").write_text(
        json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"OK metadatos clínicos Romero: {len(items)} registros")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
