"""
Convierte los PDBs de referencia a mmCIF mínimo compatible con Molstar v3.
Molstar parsea mmCIF de forma nativa y robusta; PDB tiene muchos edge cases.

Genera archivos .cif en:
  - tests/reference/structures/
  - results/data/structures/
  - results/runs/dreamy_caravaggio/data/structures/

También actualiza manifest_structures.json para apuntar a .pdb (los PDB
normalizados ya deberían funcionar; los CIF son el fallback).
"""
from pathlib import Path

STRUCTS = [
    ("/workspace/tests/reference/structures/PIK3CA_WT.pdb",     "PIK3CA", "WT"),
    ("/workspace/tests/reference/structures/PIK3CA_H1047R.pdb", "PIK3CA", "H1047R"),
]

OUTPUT_DIRS = [
    Path("/workspace/tests/reference/structures"),
    Path("/workspace/results/data/structures"),
    Path("/workspace/results/runs/dreamy_caravaggio/data/structures"),
]

try:
    from Bio.PDB import PDBParser, MMCIFIO
    HAS_BIO = True
except ImportError:
    HAS_BIO = False
    print("ERROR: biopython no disponible")
    raise


def convert(src: Path, gene: str, variant: str) -> bytes:
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure(f"{gene}_{variant}", str(src))

    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".cif", delete=False) as tmp:
        tmp_path = tmp.name

    io = MMCIFIO()
    io.set_structure(structure)
    io.save(tmp_path)

    content = Path(tmp_path).read_bytes()
    os.unlink(tmp_path)
    return content


for src_str, gene, variant in STRUCTS:
    src = Path(src_str)
    if not src.exists():
        print(f"SKIP (no existe): {src}")
        continue

    cif_bytes = convert(src, gene, variant)
    cif_name  = src.stem + ".cif"

    for out_dir in OUTPUT_DIRS:
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / cif_name
        out.write_bytes(cif_bytes)
        print(f"  ✓ {out}  ({len(cif_bytes)//1024} KB)")

print("Done.")
