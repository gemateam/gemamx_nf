#!/usr/bin/env python3
"""PREP_LIGAND — un fármaco: SMILES (catálogo) -> PDBQT listo para Vina.

Pasos:
  1. Lee el SMILES canónico de assets/drug_catalog.csv (sin descargas de red).
  2. RDKit: AddHs + ETKDGv3 (randomSeed = --seed) + MMFF94.
  3. Meeko 0.8: MoleculePreparation -> PDBQTWriterLegacy.

Una unidad de trabajo por invocación. Requiere la imagen
`gemamx-nf-docking:1.0.0` (Meeko 0.8 compatible con RDKit 2026.03).
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from rdkit import Chem, RDLogger
from rdkit.Chem import AllChem, rdMolDescriptors
from rdkit.Chem.MolStandardize import rdMolStandardize
from meeko import MoleculePreparation, PDBQTWriterLegacy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import die, sha256_file, sha256_text, write_json  # noqa: E402

RDLogger.DisableLog("rdApp.*")


def load_catalog_row(catalog_path: str, drug: str) -> dict[str, str]:
    with open(catalog_path, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if row.get("name", "").strip().lower() == drug.strip().lower():
            if not row.get("smiles", "").strip():
                die(f"el catálogo no tiene SMILES para {drug}")
            return row
    known = ", ".join(sorted(r.get("name", "") for r in rows))
    die(f"fármaco no encontrado en el catálogo: {drug!r}. Disponibles: {known}")


def build_molecule(smiles: str, seed: int) -> tuple[Chem.Mol, str]:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        die(f"RDKit no pudo interpretar el SMILES: {smiles}")

    # Quitar sales/contraiones: conservar el fragmento mayor.
    mol = rdMolStandardize.LargestFragmentChooser().choose(mol)
    mol = Chem.AddHs(mol)

    params = AllChem.ETKDGv3()
    params.randomSeed = seed
    if AllChem.EmbedMolecule(mol, params) != 0:
        die("RDKit no pudo generar el conformero 3D (ETKDGv3)")

    if AllChem.MMFFHasAllMoleculeParams(mol):
        status = AllChem.MMFFOptimizeMolecule(mol, maxIters=1000)
        forcefield = "MMFF94"
        if status != 0:
            print("AVISO: MMFF94 no convergió; se usa la geometría embebida", file=sys.stderr)
    else:
        AllChem.UFFOptimizeMolecule(mol, maxIters=1000)
        forcefield = "UFF"

    return mol, forcefield


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepara un ligando PDBQT desde SMILES")
    parser.add_argument("--catalog", required=True, help="CSV de fármacos")
    parser.add_argument("--drug", required=True, help="nombre exacto del fármaco")
    parser.add_argument("--out", required=True, help="PDBQT de salida")
    parser.add_argument("--meta", required=True, help="JSON con metadatos del ligando")
    parser.add_argument("--seed", type=int, default=42, help="semilla de ETKDGv3")
    args = parser.parse_args()

    row = load_catalog_row(args.catalog, args.drug)
    smiles = row["smiles"].strip()
    mol, forcefield = build_molecule(smiles, args.seed)

    setups = MoleculePreparation().prepare(mol)
    if not setups:
        die("Meeko no generó ningún setup para el ligando")
    pdbqt_text, ok, error = PDBQTWriterLegacy.write_string(setups[0])
    if not ok or not pdbqt_text:
        die(f"Meeko no pudo escribir el PDBQT: {error or 'error desconocido'}")
    if "ROOT" not in pdbqt_text or "ATOM" not in pdbqt_text:
        die("el PDBQT generado no contiene ROOT/ATOM")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(pdbqt_text, encoding="ascii", newline="\n")

    meta = {
        "drug": row["name"].strip(),
        "chembl_id": row.get("chembl_id", "").strip(),
        "target": row.get("target", "").strip(),
        "status": row.get("status", "").strip(),
        "smiles": smiles,
        "seed": args.seed,
        "forcefield": forcefield,
        "atoms": mol.GetNumAtoms(),
        "heavy_atoms": mol.GetNumHeavyAtoms(),
        "formula": rdMolDescriptors.CalcMolFormula(mol),
        "pdbqt_file": out.name,
        "pdbqt_sha256": sha256_file(out),
        "smiles_sha256": sha256_text(smiles),
        "pdbqt_atoms": sum(1 for line in pdbqt_text.splitlines() if line.startswith("ATOM")),
    }
    write_json(args.meta, meta, sort_keys=True)
    print(f"OK {meta['drug']}: {meta['pdbqt_atoms']} átomos -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
