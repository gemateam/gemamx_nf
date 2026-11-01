"""
Normaliza los PDBs de referencia para que sean compatibles con PDBe Molstar v3:
  1. Renumera residuos desde 1 (Molstar espera numeración continua)
  2. Agrega HEADER, REMARK y END obligatorios
  3. Actualiza el sidecar `<pdb>.json` para que `model_start` siga siendo la
     posición real del primer residuo en la proteína (si el PDB original usa
     numeración de proteína) y `model_resseq_*` refleje la renumeración.
  4. Escribe en /workspace/tests/reference/structures/ Y en /workspace/results/data/structures/
"""
import json
from pathlib import Path

STRUCTS = [
    ("/workspace/tests/reference/structures/PIK3CA_WT.pdb",      "PIK3CA",  "WT"),
    ("/workspace/tests/reference/structures/PIK3CA_H1047R.pdb",  "PIK3CA",  "H1047R"),
]

OUTPUT_DIRS = [
    Path("/workspace/tests/reference/structures"),
    Path("/workspace/results/data/structures"),
    Path("/workspace/results/runs/dreamy_caravaggio/data/structures"),
]


def normalize_pdb(src: Path, gene: str, variant: str) -> tuple[str, int, int]:
    """Devuelve (contenido PDB, primer resSeq original, nº de residuos)."""
    lines = src.read_text().splitlines()

    # Recopilar líneas ATOM/HETATM y renumerar residuos desde 1
    atom_lines = [l for l in lines if l.startswith(("ATOM", "HETATM"))]

    # Mapa de renumeración: resseq original → nuevo
    seen = {}
    counter = 0
    renumber_map = {}
    for line in atom_lines:
        resseq_str = line[22:26]
        if resseq_str not in seen:
            counter += 1
            seen[resseq_str] = counter
        renumber_map[resseq_str] = seen[resseq_str]

    # Reescribir con numeración nueva
    new_atoms = []
    for line in atom_lines:
        resseq_str = line[22:26]
        new_seq = renumber_map[resseq_str]
        new_line = line[:22] + f"{new_seq:4d}" + line[26:]
        new_atoms.append(new_line)

    title = f"GEMAMX {gene} {variant} (renumbered fragment)"
    header = f"HEADER    {title:<40}  01-JAN-26   GEMX\n"
    remark = f"REMARK   1 GEMAMX pipeline — {gene} {variant} — residues renumbered 1..{counter}\n"

    first_original = int(atom_lines[0][22:26]) if atom_lines else 1
    return header + remark + "\n".join(new_atoms) + "\nEND\n", first_original, counter


def update_sidecar(src: Path, first_original: int, residues: int) -> None:
    """Mantiene `model_start` coherente con la renumeración del PDB.

    Si el PDB original ya usaba numeración de proteína (p. ej. 957..1068), el
    primer resSeq ES la posición en la proteína y debe pasar a `model_start`.
    Si ya empezaba en 1, se respeta el `model_start` existente (el offset no
    es deducible del fichero).
    """
    sidecar = src.with_suffix(".json")
    if not sidecar.is_file():
        print(f"  WARN: sin sidecar para {src.name}; no se puede fijar model_start")
        return

    meta = json.loads(sidecar.read_text())
    if first_original != 1:
        meta["model_start"] = first_original
    meta["model_resseq_start"] = 1
    meta["model_resseq_end"] = residues
    meta["model_length"] = residues
    meta["residues"] = residues
    sidecar.write_text(json.dumps(meta, indent=4, sort_keys=False) + "\n")
    print(f"  ✓ {sidecar}  (model_start={meta.get('model_start')})")


for src_str, gene, variant in STRUCTS:
    src = Path(src_str)
    if not src.exists():
        print(f"SKIP (no existe): {src}")
        continue

    content, first_original, residues = normalize_pdb(src, gene, variant)
    fname = src.name

    for out_dir in OUTPUT_DIRS:
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / fname
        out.write_text(content)
        lines = content.count("\n")
        print(f"  ✓ {out}  ({lines} líneas)")

    update_sidecar(src, first_original, residues)

print("Done.")
