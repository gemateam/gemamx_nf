#!/usr/bin/env python3
"""Prueba del lector XLSX de INGEST_ROMERO: celdas vacías y marcadores "-".

No necesita dependencias externas: construye un XLSX mínimo en un directorio
temporal y comprueba que

  - una celda omitida en medio de la fila no desplaza las columnas;
  - las cadenas en línea (`t="inlineStr"`) se leen;
  - las filas de solo marcadores de vacío se descartan;
  - la capa de campos (`cell_text`) convierte "-", ".", "NA", "N/A", "#N/A" y
    "—" en "";
  - la cabecera se elige por su número de fila, así que una fila vacía presente
    no la desplaza, y `required` avisa si el fichero cambia de forma;
  - una columna sin nombre recibe clave posicional y dos nombres iguales fallan;
  - el extractor clínico (`extract_clinical_romero`) usa ese mismo lector;
  - la capa clínica (`clean`) convierte los marcadores en `None` pero conserva
    el cero (0 embarazos es un dato, no un ausente).

El lector de hojas conserva el texto tal cual (el "-" de los alelos MAF es
notación de deleción/inserción); la normalización ocurre al extraer campos.

Uso: python3 tests/test_xlsx_parser.py
"""

from __future__ import annotations

import sys
import shutil
import contextlib
import io
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))

from ingest_romero import cell_text, sheet_to_dicts  # noqa: E402
import build_jsons as bj                             # noqa: E402
import extract_clinical_romero as ecr                # noqa: E402
import ingest_romero as ir                           # noqa: E402

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
        # fila 2: presente pero vacía. Antes desplazaba la cabecera una posición;
        # ahora la cabecera se elige por su número de fila (3) y eso no importa.
        [],
        # fila 3: cabecera
        [c(f"{col}3", name) for col, name in
         zip("ABCDE", ("Gen", "G1", "G2", "Alelo", "Nota"))],
        # fila 4: fila densa con marcadores explícitos
        [c("A4", "AKT1"), c("B4", "v1"), c("C4", "v2"),
         c("D4", "-"), c("E4", "NA")],
        # fila 5: sin celda B (hueco en medio) y con celda en línea
        [c("A5", "PIK3CA"), c("C5", "z", inline=True),
         c("D5", "1", numeric=True), c("E5", "—")],
        # fila 6: cadena en línea, número y marcadores
        [c("A6", "TP53"), c("B6", "inline", inline=True),
         c("C6", "2.5", numeric=True), c("D6", "-"), c("E6", ".")],
        # fila 7: solo marcadores de vacío → se descarta
        [c("A7", "-"), c("B7", "NA"), c("C7", "N/A"),
         c("D7", "."), c("E7", "—")],
    ]
    body = "".join(
        (f'<row r="{i}">{"".join(cells)}</row>' if cells else f'<row r="{i}"/>')
        for i, cells in enumerate(rows, 1))
    return (f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<worksheet xmlns="{MAIN_NS}"><sheetData>{body}</sheetData></worksheet>')


def col_letters(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def build_minimal_xlsx(path: Path, header: list[str], data: list[list[str]], *,
                       sheet: str = "Hoja", header_at: int = 1) -> None:
    """XLSX mínimo con celdas de texto y la cabecera en `header_at`.

    `header_at` es el número de fila de Excel: las filas anteriores se escriben
    vacías pero presentes, como en los suplementarios reales.
    """
    values: list[str] = []

    def shared_id(text: str) -> int:
        if text not in values:
            values.append(text)
        return values.index(text)

    filas: list[str] = [f'<row r="{i}"/>' for i in range(1, header_at)]
    grid = [header] + data
    filas += [
        f'<row r="{r}">' + "".join(
            f'<c r="{col_letters(i)}{r}" t="s"><v>{shared_id(v)}</v></c>'
            for i, v in enumerate(row)) + "</row>"
        for r, row in enumerate(grid, header_at)]
    body = "".join(filas)
    sst = (f'<?xml version="1.0" encoding="UTF-8"?>'
           f'<sst xmlns="{MAIN_NS}" count="{len(values)}" '
           f'uniqueCount="{len(values)}">'
           + "".join(f"<si><t>{v}</t></si>" for v in values) + "</sst>")
    sheet_xml = (f'<?xml version="1.0" encoding="UTF-8"?>'
                 f'<worksheet xmlns="{MAIN_NS}"><sheetData>{body}</sheetData></worksheet>')
    workbook = (f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}">'
                f'<sheets><sheet name="{sheet}" sheetId="1" r:id="rId1"/></sheets>'
                f'</workbook>')
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", RELS)
        zf.writestr("xl/sharedStrings.xml", sst)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)


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


def check_raises(fn, fragment: str, message: str) -> None:
    """Comprueba que `fn` lanza ValueError y que el mensaje contiene `fragment`."""
    try:
        fn()
    except ValueError as exc:
        check(fragment in str(exc), message)
        return
    raise AssertionError(f"{message}: no lanzó ValueError")


def make_tmpdir() -> Path:
    """Directorio de trabajo escribible.

    `tempfile.mkdtemp` crea el directorio con modo 0700; en Windows eso puede
    dejarlo sin permisos heredados e inaccesible incluso para quien lo creó.
    Se usa un directorio con los permisos por defecto (heredados del padre),
    primero en el temporal del sistema y, si no se puede, junto al repositorio.
    """
    candidates = [Path(tempfile.gettempdir()) / "gemamx-xlsx-test",
                  Path(__file__).resolve().parent.parent / ".tmp_xlsx_test"]
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


def main() -> int:
    print("> Marcadores de vacío (cell_text)")
    for raw in ("-", "—", "–", ".", "NA", "n/a", "None", "  ", "#N/A", "#n/a"):
        check(cell_text(raw) == "", f"cell_text({raw!r}) == ''")
    for raw in ("A", "T", "Missense_Mutation", "0", "SNP"):
        check(cell_text(raw) == raw, f"cell_text({raw!r}) se conserva")

    tmpdir = make_tmpdir()
    try:
        xlsx = tmpdir / "mini.xlsx"
        build_xlsx(xlsx)
        rows = sheet_to_dicts(xlsx, "Hoja", header_row=3,
                              required=("Gen", "G1", "Alelo"))
        # El extractor clínico debe usar el mismo lector, no una copia propia.
        clinical_rows = ecr.sheet_to_dicts(xlsx, "Hoja", header_row=3)

        print("> Cabecera por número de fila y nombres de columna")
        check_raises(lambda: sheet_to_dicts(xlsx, "Hoja", header_row=2),
                     "cabecera", "una fila vacía presente no se toma como cabecera")
        check_raises(lambda: sheet_to_dicts(xlsx, "Hoja", header_row=3,
                                            required=("NoExiste",)),
                     "faltan columnas", "`required` detecta un cambio de cabecera")

        dup = tmpdir / "dup.xlsx"
        build_minimal_xlsx(dup, ["Gen", "Gen", "Nota"], [["A", "B", "C"]])
        check_raises(lambda: sheet_to_dicts(dup, "Hoja", header_row=1),
                     "duplicada", "dos columnas con el mismo nombre son un error")

        unnamed = tmpdir / "unnamed.xlsx"
        build_minimal_xlsx(unnamed, ["Gen", "", "Nota"], [["A", "B", "C"]])
        sin_nombre = sheet_to_dicts(unnamed, "Hoja", header_row=1)[0]
        check(list(sin_nombre) == ["Gen", "_col_2", "Nota"],
              "una columna sin nombre recibe clave posicional y no se pierde")
        check(sin_nombre["_col_2"] == "B",
              "el dato de la columna sin nombre se conserva")

        print("> Contrato vacío: la ingesta y build_jsons fallan sin escribir nada")
        maf = tmpdir / "maf.xlsx"
        build_minimal_xlsx(
            maf,
            header=["Hugo Symbol", "Chromosome", "Start Position", "End Position",
                    "Variant Classification", "Variant Type", "Reference Allele",
                    "Tumor Seq Allele1", "Tumor Seq Allele2",
                    "Tumor Sample Barcode", "Center"],
            data=[["PIK3CA", "3", "178952085", "178952086", "Missense_Mutation",
                   "SNP", "C", "C", "T", "S1", "FUCAM"]],
            sheet="HM maf", header_at=2)
        drv = tmpdir / "drv.xlsx"
        build_minimal_xlsx(
            drv,
            header=["Gene", "gdna", "cdna", "Exon", "Protein", "Protein change",
                    "Driver", "Consequence", "Disrupting driver mut prediction",
                    "Gene role mutation", "Known variant reference"],
            data=[["PIK3CA", "chr3:g.178952085C>T", "c.3140A>G", "21",
                   "p.His1047Arg", "H/R", "Yes", "missense", "", "Oncogene", ""]],
            sheet="Driver mutation in HM", header_at=3)

        out = tmpdir / "contrato_vacio"
        argv = sys.argv
        err = io.StringIO()
        sys.argv = ["ingest_romero.py", "--maf", str(maf), "--drivers", str(drv),
                    "--outdir", str(out), "--genes", "AKT1", "--max-variants", "5"]
        try:
            with contextlib.redirect_stderr(err):
                ir.main()
            raise AssertionError("la ingesta debía fallar sin variantes priorizadas")
        except SystemExit as exc:
            check(exc.code == 1, "sin variantes priorizadas: sale con código 1")
            check("no quedó ninguna variante priorizada" in err.getvalue(),
                  "sin variantes priorizadas: mensaje explicativo")
        finally:
            sys.argv = argv
        check(not (out / "top_variants.json").exists(),
              "sin variantes priorizadas: no se escribe ningún contrato")

        vacio = tmpdir / "top_vacio.json"
        vacio.write_text("[]", encoding="utf-8")
        raw = tmpdir / "raw.json"
        raw.write_text("[]", encoding="utf-8")
        stats = tmpdir / "stats.json"
        stats.write_text("{}", encoding="utf-8")
        err = io.StringIO()
        sys.argv = ["build_jsons.py", "--top", str(vacio), "--raw", str(raw),
                    "--stats", str(stats), "--outdir", str(tmpdir / "bj")]
        try:
            with contextlib.redirect_stderr(err):
                bj.main()
            raise AssertionError("build_jsons debía rechazar un top vacío")
        except SystemExit as exc:
            check(exc.code == 1, "build_jsons: un top vacío sale con código 1")
            check("top_variants vacío" in err.getvalue(),
                  "build_jsons: un top vacío se rechaza con mensaje")
        finally:
            sys.argv = argv
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("> Lectura de la hoja")
    check(len(rows) == 3, "la fila de solo marcadores de vacío se descarta")
    check(clinical_rows == rows,
          "el extractor clínico usa el lector por referencia (mismo resultado)")
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

    print("> Capa clínica: marcadores de vacío y cero")
    for raw in (None, "", "  ", "-", "—", "–", ".", "NA", "n/a", "N/A", "None", "#N/A"):
        check(ecr.clean(raw) is None, f"clean({raw!r}) es ausente")
    for raw in ("I", "IDC", "Negative", "T3N1M0", "Basal"):
        check(ecr.clean(raw) == raw, f"clean({raw!r}) se conserva")
    check(ecr.clean(0) == "0", "clean(0) conserva el cero (no lo confunde con vacío)")
    check(ecr.parse_int(0) == 0, "parse_int(0) == 0")
    check(ecr.parse_int("-") is None, "parse_int('-') es ausente")
    check(ecr.parse_int("55.0") == 55, "parse_int acepta el formato numérico de Excel")

    rec = ecr.normalize_row({"Tumor Sample Barcode": "S1", "Age": "55",
                             "Number of pregnancies": 0,
                             "Age at menopuse": "NA"})
    check(rec["age"] == 55, "normalize_row: edad entera")
    check(rec["number_of_pregnancies"] == 0, "normalize_row: 0 embarazos no se pierde")
    check(rec["age_at_menopause"] is None, "normalize_row: 'NA' es ausente")
    check(rec["sample_id"] == "S1", "normalize_row: identificador de muestra")

    print("OK Parser XLSX")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
