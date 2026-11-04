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

Celdas vacías: Excel puede representarlas como `<c>` ausente, `<c/>` sin valor
o el marcador textual "-" (también ".", "NA", "N/A" y el error `#N/A`). El lector
se guía por la referencia `r` de cada celda para no desplazar columnas y
`cell_text()` convierte esos marcadores en "" en los campos textuales. En las
columnas de alelos el "-"
se conserva: en el formato MAF significa deleción o inserción, no celda vacía.
La cabecera se localiza por su número de fila de Excel (2 en el MAF, 3 en los
drivers) y `sheet_to_dicts(..., required=...)` falla si el fichero cambia de
forma, en vez de producir columnas vacías.

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
from collections.abc import Sequence
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

# Marcadores de celda vacía en los XLSX del artículo: el guión es el habitual,
# pero también aparecen ".", "NA" y "N/A" en otras hojas del mismo suplemento.
# "#n/a" cubre las celdas de error de Excel (`t="e"`, que el lector entrega como
# texto): sin él, un `#N/A` acabaría siendo el nombre de un gen.
NULL_TOKENS = {"", "-", "—", "–", "na", "n/a", "nan", "null", "none", ".", "#n/a"}


def cell_text(value: object) -> str:
    """Texto de una celda, con los marcadores de vacío normalizados a ""."""
    text = str(value if value is not None else "").strip()
    return "" if text.lower() in NULL_TOKENS else text


def col_index(ref: str) -> int:
    """Índice 0-based de la columna de una referencia de celda ("A1", "AB12")."""
    index = 0
    for ch in ref:
        if not ch.isalpha():
            break
        index = index * 26 + (ord(ch.upper()) - 64)
    return index - 1


def load_xlsx_sheet(path: Path, sheet_name: str) -> tuple[list[int], list[list[str]]]:
    """Lee una hoja como (números de fila, filas de texto).

    Excel omite las celdas vacías del XML: si los valores se concatenan en orden
    de aparición, un hueco desplaza el resto de la fila. Por eso cada valor se
    coloca en el índice de su atributo `r` y los huecos quedan como "".

    Se conserva además el número de fila de Excel (`r` de `<row>`) para que la
    cabecera se localice por su fila real y no por su posición entre las filas
    presentes: una fila vacía intercalada ya no la desplaza.

    Valores posibles: cadena compartida (`t="s"`), cadena en línea
    (`t="inlineStr"`) o número/fórmula (`<v>` sin `t`).
    """
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
        numbers: list[int] = []
        rows: list[list[str]] = []
        for row in sheet_xml.findall(".//main:sheetData/main:row", NS):
            raw_number = row.attrib.get("r")
            numbers.append(int(raw_number) if raw_number and raw_number.isdigit()
                           else (numbers[-1] + 1 if numbers else 1))
            values: list[str] = []
            for cell in row.findall("main:c", NS):
                ctype = cell.attrib.get("t")
                if ctype == "inlineStr":
                    value = "".join(t.text or ""
                                    for t in cell.findall(".//main:t", NS))
                else:
                    v_el  = cell.find("main:v", NS)
                    value = "" if (v_el is None or v_el.text is None) else v_el.text
                if ctype == "s" and value.isdigit():
                    idx   = int(value)
                    value = shared[idx] if idx < len(shared) else value

                ref = cell.attrib.get("r")
                if not ref:
                    values.append(value)
                    continue
                idx = col_index(ref)
                if idx >= len(values):
                    values.extend([""] * (idx + 1 - len(values)))
                values[idx] = value
            rows.append(values)
        return numbers, rows


def load_xlsx_sheet_rows(path: Path, sheet_name: str) -> list[list[str]]:
    """Compatibilidad: las filas, sin sus números de fila de Excel."""
    return load_xlsx_sheet(path, sheet_name)[1]


def sheet_to_dicts(path: Path, sheet_name: str, header_row: int,
                   required: Sequence[str] = ()) -> list[dict[str, str]]:
    """Filas de datos como diccionarios, con la cabecera de `header_row`.

    `header_row` es el número de fila de Excel (1-based), no la posición entre
    las filas presentes: así una fila vacía intercalada no desplaza la cabecera.
    `required` son etiquetas que deben existir; si el fichero cambia de forma se
    falla con un mensaje explícito en lugar de producir columnas vacías.

    Las columnas sin nombre reciben una clave posicional (`_col_<n>`) para no
    colapsar varias en la clave "" y perder datos en silencio; dos columnas con
    el mismo nombre son un error.
    """
    numbers, rows = load_xlsx_sheet(path, sheet_name)
    by_number = dict(zip(numbers, rows))
    header = by_number.get(header_row)
    if header is None or not any(cell_text(v) for v in header):
        raise ValueError(
            f"cabecera vacía o inexistente en la fila {header_row} de "
            f"{path.name!r} hoja {sheet_name!r} "
            f"(filas presentes: {numbers[:6]}{'…' if len(numbers) > 6 else ''})")

    names: list[str] = []
    seen: set[str] = set()
    for i, raw_name in enumerate(header):
        name = cell_text(raw_name) or f"_col_{i + 1}"
        if name in seen:
            raise ValueError(
                f"cabecera duplicada {name!r} en {path.name!r} hoja {sheet_name!r}")
        seen.add(name)
        names.append(name)

    faltan = [label for label in required if label not in seen]
    if faltan:
        raise ValueError(
            f"faltan columnas {faltan} en {path.name!r} hoja {sheet_name!r}: "
            f"¿cambió la fila de cabecera? encontradas: {names[:8]}…")

    width  = len(header)
    result = []
    for number, row in zip(numbers, rows):
        if number <= header_row:
            continue
        # Una fila con solo marcadores de vacío ("-", "NA") no es un dato.
        if not any(cell_text(v) for v in row):
            continue
        padded = row + [""] * (width - len(row))
        result.append({names[i]: padded[i] for i in range(width)})
    return result


# ── Utilidades ────────────────────────────────────────────────────────────────

def parse_int(value: object, default: int = 0) -> int:
    """Entero de una celda; vacía o con marcador de vacío ("-") → `default`."""
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
        gene = cell_text(row.get("Gene"))
        key  = (gene, parsed["chromosome"], parsed["start_position"],
                parsed["reference_allele"], parsed["tumor_seq_allele2"])
        lookup[key] = {
            "protein_change":         normalize_protein_change(
                row.get("Protein", ""), row.get("Protein change", "")),
            "driver":                 cell_text(row.get("Driver")),
            "consequence":            cell_text(row.get("Consequence")),
            "gene_role_mutation":     cell_text(row.get("Gene role mutation")),
            "known_variant_reference": cell_text(row.get("Known variant reference")),
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
    hm_maf_rows = sheet_to_dicts(
        maf_path, "HM maf", header_row=2,
        required=("Hugo Symbol", "Chromosome", "Start Position",
                  "Reference Allele", "Tumor Seq Allele2", "Variant Classification"))
    print(f"Leyendo drivers: {drivers_path.name}")
    driver_rows  = sheet_to_dicts(
        drivers_path, "Driver mutation in HM", header_row=3,
        required=("Gene", "gdna", "Protein", "Protein change", "Driver"))

    driver_lookup = build_driver_lookup(driver_rows)
    # Variantes driver que nunca encuentran su fila en el MAF: se avisa al final.
    driver_keys_usadas: set[tuple] = set()

    # ── M1+M2: normalización, priorización y estadísticas en una sola pasada ──
    raw_mutations: list[dict] = []
    samples: set[str] = set()
    gene_counts: Counter = Counter()
    type_counts: Counter = Counter()
    counts: dict[tuple, dict] = defaultdict(
        lambda: {"frequency": 0, "chromosome": "?", "start_position": 0})

    for row in hm_maf_rows:
        # Las columnas de alelos conservan el "-": en MAF significa deleción o
        # inserción, no celda vacía. El resto de campos sí normaliza vacíos.
        gene  = cell_text(row.get("Hugo Symbol"))
        chrom = cell_text(row.get("Chromosome"))
        start = parse_int(row.get("Start Position", 0))
        ref   = str(row.get("Reference Allele", "")).strip()
        alt   = (str(row.get("Tumor Seq Allele2", "")).strip()
                 or str(row.get("Tumor Seq Allele1", "")).strip())
        driver_key = (gene, chrom, start, ref, alt)
        driver = driver_lookup.get(driver_key, {})
        if driver:
            driver_keys_usadas.add(driver_key)

        classification = cell_text(row.get("Variant Classification"))
        sample_id      = cell_text(row.get("Tumor Sample Barcode"))
        protein_change = driver.get("protein_change")

        raw_mutations.append({
            "hugo_symbol":            gene,
            "variant_classification": classification,
            "variant_type":           cell_text(row.get("Variant Type")),
            "protein_change":         protein_change,
            "sample_id":              sample_id,
            "chromosome":             chrom,
            "start_position":         start,
            "end_position":           parse_int(row.get("End Position", 0)),
            "reference_allele":       ref,
            "tumor_seq_allele2":      alt,
            "source_center":          cell_text(row.get("Center")),
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

    # Trazabilidad del cruce: los drivers sin fila MAF no se anotan y antes
    # desaparecían en silencio. La causa habitual es que el llamador del MAF no
    # reportó esa variante (no un problema del lector).
    sin_par = [key for key in driver_lookup if key not in driver_keys_usadas]
    if sin_par:
        print(f"AVISO: {len(sin_par)} de {len(driver_lookup)} variantes driver no "
              f"encuentran fila en el MAF y no se anotan: {sin_par[:5]}")

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
