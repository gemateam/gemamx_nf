#!/usr/bin/env python3
"""INGEST_ROMERO — M1/M2 del pipeline V2.

Parsea los suplementarios XLSX de Romero-Córdoba 2021 (Nature Communications)
y produce los JSON de ingesta/priorización que usa el resto del pipeline.

Entradas:
  --maf      41467_2021_22478_MOESM8_ESM.xlsx  (hoja: HM maf)
  --drivers  41467_2021_22478_MOESM9_ESM.xlsx  (hoja: Driver mutation in HM)

Salidas en --outdir:
  raw_mutations.json    — 28 114 mutaciones normalizadas
  top_variants.json     — variantes priorizadas (missense en KEY_GENES)
  mutation_stats.json   — distribución por gen/tipo

Derivado del script original v2/scripts/ingest_romero.py; refactorizado para
aceptar rutas por argumento (portable dentro de cualquier contenedor Docker).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET

# ── Constantes ────────────────────────────────────────────────────────────────
KEY_GENES = [
    "PIK3CA", "TP53", "ERBB2", "BRCA1", "BRCA2",
    "CDH1", "GATA3", "MAP3K1", "KMT2C", "PTEN",
    "RB1", "ARID1A", "SF3B1", "AKT1", "CBFB",
]

NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel":  "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkg":  "http://schemas.openxmlformats.org/package/2006/relationships",
}

AA3_TO_1 = {
    "Ala": "A", "Arg": "R", "Asn": "N", "Asp": "D", "Cys": "C",
    "Gln": "Q", "Glu": "E", "Gly": "G", "His": "H", "Ile": "I",
    "Leu": "L", "Lys": "K", "Met": "M", "Phe": "F", "Pro": "P",
    "Ser": "S", "Thr": "T", "Trp": "W", "Tyr": "Y", "Val": "V",
}


# ── Parser XLSX nativo (sin pandas/openpyxl) ──────────────────────────────────

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
            raise ValueError(f"Hoja no encontrada: {sheet_name!r} en {path.name}")

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


# ── Utilidades ────────────────────────────────────────────────────────────────

def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def parse_gdna(gdna: str) -> dict | None:
    m = re.match(
        r"chr(?P<chr>[^:]+):g\.(?P<pos>\d+)(?P<ref>[A-Z\-]+)>(?P<alt>[A-Z\-]+)",
        gdna or "",
    )
    if not m:
        return None
    return {
        "chromosome":      m.group("chr"),
        "start_position":  int(m.group("pos")),
        "reference_allele": m.group("ref"),
        "tumor_seq_allele2": m.group("alt"),
    }


def normalize_protein_change(protein_value: str, short_change: str) -> str | None:
    pv = str(protein_value or "").strip()
    sc = str(short_change  or "").strip()
    m  = re.search(r"p\.([A-Z][a-z]{2})(\d+)([A-Z][a-z]{2})", pv)
    if m:
        wt = AA3_TO_1.get(m.group(1), "")
        mt = AA3_TO_1.get(m.group(3), "")
        if wt and mt:
            return f"{wt}{m.group(2)}{mt}"
    if sc and re.match(r"^[A-Z]/[A-Z]$", sc):
        pm = re.search(r"(\d+)", pv)
        if pm:
            wt, mt = sc.split("/")
            return f"{wt}{pm.group(1)}{mt}"
    return None


def classify_variant(cohort_pct: float) -> str:
    if cohort_pct >= 5.0:
        return "Patogénica"
    if cohort_pct >= 1.0:
        return "Probable Patogénica"
    if cohort_pct >= 0.5:
        return "VUS"
    return "Baja Frecuencia"


def build_driver_lookup(driver_rows: list[dict]) -> dict:
    lookup: dict = {}
    for row in driver_rows:
        parsed = parse_gdna(row.get("gdna", ""))
        if not parsed:
            continue
        gene = str(row.get("Gene", "")).strip()
        key  = (gene, parsed["chromosome"], parsed["start_position"],
                parsed["reference_allele"], parsed["tumor_seq_allele2"])
        lookup[key] = {
            "protein_change":         normalize_protein_change(
                row.get("Protein", ""), row.get("Protein change", "")),
            "driver":                 str(row.get("Driver", "")).strip(),
            "consequence":            str(row.get("Consequence", "")).strip(),
            "gene_role_mutation":     str(row.get("Gene role mutation", "")).strip(),
            "known_variant_reference": str(row.get("Known variant reference", "")).strip(),
        }
    return lookup


# ── Lógica principal ──────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Ingestión del cohorte Romero-Córdoba 2021")
    ap.add_argument("--maf",     required=True,
                    help="MOESM8_ESM.xlsx — hoja 'HM maf'")
    ap.add_argument("--drivers", required=True,
                    help="MOESM9_ESM.xlsx — hoja 'Driver mutation in HM'")
    ap.add_argument("--outdir",  required=True,
                    help="directorio de salida")
    ap.add_argument("--genes",   default=",".join(KEY_GENES),
                    help="genes clave separados por coma")
    ap.add_argument("--max-variants", type=int, default=49,
                    help="máximo de variantes en top_variants.json")
    ap.add_argument("--dataset", default="Romero-Cordoba 2021 HM",
                    help="etiqueta del dataset")
    args = ap.parse_args()

    maf_path     = Path(args.maf)
    drivers_path = Path(args.drivers)
    outdir       = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    key_genes = {g.strip().upper() for g in args.genes.split(",") if g.strip()}

    print(f"Leyendo MAF: {maf_path.name}")
    hm_maf_rows = sheet_to_dicts(maf_path, "HM maf", header_row_idx=1)
    print(f"Leyendo drivers: {drivers_path.name}")
    driver_rows  = sheet_to_dicts(drivers_path, "Driver mutation in HM", header_row_idx=1)

    driver_lookup = build_driver_lookup(driver_rows)

    # ── M1+M2: normalización, priorización y estadísticas en una sola pasada ──
    raw_mutations: list[dict] = []
    samples: set[str] = set()
    gene_counts: Counter = Counter()
    type_counts: Counter = Counter()
    counts: dict[tuple, dict] = defaultdict(
        lambda: {"frequency": 0, "chromosome": "?", "start_position": 0})

    for row in hm_maf_rows:
        gene  = str(row.get("Hugo Symbol", "")).strip()
        chrom = str(row.get("Chromosome", "")).strip()
        start = parse_int(row.get("Start Position", 0))
        ref   = str(row.get("Reference Allele", "")).strip()
        alt   = (str(row.get("Tumor Seq Allele2", "")).strip()
                 or str(row.get("Tumor Seq Allele1", "")).strip())
        driver = driver_lookup.get((gene, chrom, start, ref, alt), {})

        classification = str(row.get("Variant Classification", "")).strip()
        sample_id      = str(row.get("Tumor Sample Barcode", "")).strip()
        protein_change = driver.get("protein_change")

        raw_mutations.append({
            "hugo_symbol":            gene,
            "variant_classification": classification,
            "variant_type":           str(row.get("Variant Type", "")).strip(),
            "protein_change":         protein_change,
            "sample_id":              sample_id,
            "chromosome":             chrom,
            "start_position":         start,
            "end_position":           parse_int(row.get("End Position", 0)),
            "reference_allele":       ref,
            "tumor_seq_allele2":      alt,
            "source_center":          str(row.get("Center", "")).strip(),
            "driver_status":          driver.get("driver"),
            "consequence":            driver.get("consequence"),
            "gene_role_mutation":     driver.get("gene_role_mutation"),
            "known_variant_reference": driver.get("known_variant_reference"),
            "dataset":                args.dataset,
        })

        if sample_id:
            samples.add(sample_id)
        if gene:
            gene_counts[gene] += 1
        if classification:
            type_counts[classification] += 1

        # Filtro de priorización al vuelo: solo missense de genes clave con cambio.
        if (gene in key_genes
                and "missense" in classification.lower()
                and protein_change):
            meta = counts[(gene, protein_change)]
            meta["frequency"] += 1
            if chrom:
                meta["chromosome"] = chrom
            if start:
                meta["start_position"] = start

    total_samples = len(samples)

    top_variants: list[dict] = []
    for rank, ((gene, pc), meta) in enumerate(
        sorted(counts.items(), key=lambda kv: (-kv[1]["frequency"], kv[0][0], kv[0][1])),
        start=1,
    ):
        if rank > args.max_variants:
            break
        pct = meta["frequency"] / total_samples * 100 if total_samples else 0.0
        top_variants.append({
            "hugo_symbol":       gene,
            "protein_change":    pc,
            "chromosome":        meta["chromosome"],
            "start_position":    meta["start_position"],
            "frequency":         meta["frequency"],
            "cohort_percentage": round(pct, 6),
            "classification":    classify_variant(pct),
            "rank":              rank,
            "dataset":           args.dataset,
        })

    # ── Estadísticas (contadores acumulados en la pasada anterior) ────────────
    stats = {
        "gene_distribution":  dict(gene_counts.most_common(20)),
        "type_distribution":  dict(type_counts.most_common()),
        "total_samples":      total_samples,
        "total_mutations":    len(raw_mutations),
        "dataset":            args.dataset,
    }

    # ── Escritura (JSON compacto: mismo contenido, ~20 % menos bytes) ─────────
    def write_compact(name: str, payload: object) -> None:
        (outdir / name).write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")

    write_compact("raw_mutations.json", raw_mutations)
    write_compact("top_variants.json", top_variants)
    write_compact("mutation_stats.json", stats)

    print(f"OK ingestión Romero: {len(raw_mutations)} mutaciones, "
          f"cohorte {total_samples} muestras, "
          f"{len(top_variants)} variantes priorizadas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
