#!/usr/bin/env python3
"""Prueba del lector XLSX de INGEST_ROMERO: celdas vacías y marcadores "-".

No necesita dependencias externas: construye un XLSX mínimo en un directorio
temporal y comprueba que

  - una celda omitida en medio de la fila no desplaza las columnas;
  - las cadenas en línea (`t="inlineStr"`) se leen;
  - las filas de solo marcadores de vacío se descartan;
  - la capa de campos (`cell_text`) convierte "-", ".", "NA", "N/A" y "—" en "".

El lector de hojas conserva el texto tal cual (el "-" de los alelos MAF es
notación de deleción/inserción); la normalización ocurre al extraer campos.

Uso: python3 tests/test_xlsx_parser.py
"""

from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))

from ingest_romero import cell_text, sheet_to_dicts  # noqa: E402

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS  = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_NS  = "http://schemas.openxmlformats.org/package/2006/relationships"

STRINGS = [
    "título", "Gen", "G1", "G2", "Alelo", "Nota",   # 0-5
    "AKT1", "PIK3CA", "TP53", "v1", "v2",           # 6-10
    "-", "NA", "—", ".", "N/A",                     # 11-15
]

WORKBOOK = f"""<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}">
  <sheets><sheet name="Hoja" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""

RELS = f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="{PKG_NS}">
  <Relationship Id="rId1" Type="{REL_NS}/worksheet"
                Target="worksheets/sheet1.xml"/>
</Relationships>"""


def shared_xml() -> str:
    items = "".join(f"<si><t>{text}</t></si>" for text in STRINGS)
    return (f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<sst xmlns="{MAIN_NS}" count="{len(STRINGS)}" '
            f'uniqueCount="{len(STRINGS)}">{items}</sst>')


def c(ref: str, value: str, *, inline: bool = False, numeric: bool = False) -> str:
    if inline:
        return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'
    if numeric:
        return f'<c r="{ref}"><v>{value}</v></c>'
    return f'<c r="{ref}" t="s"><v>{STRINGS.index(value)}</v></c>'


def sheet_xml() -> str:
    rows = [
        # fila 1: título de la hoja (no es cabecera)
        [c("A1", "título")],
        # fila 2: cabecera
        [c(f"{col}2", name) for col, name in
         zip("ABCDE", ("Gen", "G1", "G2", "Alelo", "Nota"))],
        # fila 3: fila densa con marcadores explícitos
        [c("A3", "AKT1"), c("B3", "v1"), c("C3", "v2"),
         c("D3", "-"), c("E3", "NA")],
        # fila 4: sin celda B (hueco en medio) y con celda en línea
        [c("A4", "PIK3CA"), c("C4", "z", inline=True),
         c("D4", "1", numeric=True), c("E4", "—")],
        # fila 5: cadena en línea, número y marcadores
        [c("A5", "TP53"), c("B5", "inline", inline=True),
         c("C5", "2.5", numeric=True), c("D5", "-"), c("E5", ".")],
        # fila 6: solo marcadores de vacío → se descarta
        [c("A6", "-"), c("B6", "NA"), c("C6", "N/A"),
         c("D6", "."), c("E6", "—")],
    ]
    body = "".join(
        f'<row r="{i}">{"".join(cells)}</row>' for i, cells in enumerate(rows, 1))
    return (f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<worksheet xmlns="{MAIN_NS}"><sheetData>{body}</sheetData></worksheet>')


def build_xlsx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/workbook.xml", WORKBOOK)
        zf.writestr("xl/_rels/workbook.xml.rels", RELS)
        zf.writestr("xl/sharedStrings.xml", shared_xml())
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml())


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  OK  {message}")


def main() -> int:
    print("> Marcadores de vacío (cell_text)")
    for raw in ("-", "—", "–", ".", "NA", "n/a", "None", "  "):
        check(cell_text(raw) == "", f"cell_text({raw!r}) == ''")
    for raw in ("A", "T", "Missense_Mutation", "0", "SNP"):
        check(cell_text(raw) == raw, f"cell_text({raw!r}) se conserva")

    with tempfile.TemporaryDirectory() as tmp:
        xlsx = Path(tmp) / "mini.xlsx"
        build_xlsx(xlsx)
        rows = sheet_to_dicts(xlsx, "Hoja", header_row_idx=1)

    print("> Lectura de la hoja")
    check(len(rows) == 3, "la fila de solo marcadores de vacío se descarta")
    first, second, third = rows

    check(first["Gen"] == "AKT1" and first["G1"] == "v1" and first["G2"] == "v2",
          "fila densa: columnas alineadas con la cabecera")
    check(first["Alelo"] == "-", "fila densa: el '-' del alelo se conserva")

    check(second["Gen"] == "PIK3CA", "fila con hueco: primera columna intacta")
    check(second["G1"] == "", "fila con hueco: la celda omitida queda vacía")
    check(second["G2"] == "z", "fila con hueco: 'z' no se desplaza a G1")
    check(second["Alelo"] == "1", "fila con hueco: el número conserva su columna")

    check(third["G1"] == "inline", "cadena en línea (t=inlineStr) se lee")
    check(third["G2"] == "2.5", "celda numérica sin t se lee como texto")

    print("OK Parser XLSX")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
