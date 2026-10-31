"""
Normaliza los PDBs de referencia para que sean compatibles con PDBe Molstar v3:
  1. Renumera residuos desde 1 (Molstar espera numeración continua)
  2. Agrega HEADER, REMARK y END obligatorios
  3. Escribe en /workspace/tests/reference/structures/ Y en /workspace/results/data/structures/
"""
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


def normalize_pdb(src: Path, gene: str, variant: str) -> str:
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

    return header + remark + "\n".join(new_atoms) + "\nEND\n"


for src_str, gene, variant in STRUCTS:
    src = Path(src_str)
    if not src.exists():
        print(f"SKIP (no existe): {src}")
        continue

    content = normalize_pdb(src, gene, variant)
    fname = src.name

    for out_dir in OUTPUT_DIRS:
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / fname
        out.write_text(content)
        lines = content.count("\n")
        print(f"  ✓ {out}  ({lines} líneas)")

print("Done.")
