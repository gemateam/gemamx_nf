"""
M3: Generador del Espacio Combinatorio — GEMAGENTICDI
GEN-MAMA-MX · Capa 3: Matriz de Agentes Clínicos

Construye la matriz N×M de inhibidores × blancos moleculares,
aplica filtros ADMET usando RDKit y reduce el espacio via clustering.
"""

import json
import logging
import warnings
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml
from rdkit import Chem
from rdkit.Chem import Descriptors, Crippen, Lipinski
from rdkit.Chem import FilterCatalog
from rdkit.Chem import AllChem
from rdkit import DataStructs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore")


def load_config(config_path: str) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def load_compound_library(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    logger.info(f"Loaded {len(df)} compounds from library")
    return df


def compute_admet_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula propiedades ADMET proxy usando RDKit descriptors."""

    # Initialize PAINS filter
    params = FilterCatalog.FilterCatalogParams()
    params.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS)
    catalog = FilterCatalog.FilterCatalog(params)

    mols = []
    valid_mask = []

    for smiles in df["smiles"]:
        if pd.isna(smiles) or smiles == "NA":
            mols.append(None)
            valid_mask.append(False)
            continue
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            mols.append(None)
            valid_mask.append(False)
        else:
            mols.append(mol)
            valid_mask.append(True)

    df = df.copy()
    df["_mol"] = mols
    df["_valid_smiles"] = valid_mask

    records = []
    for idx, row in df.iterrows():
        if row["_mol"] is None:
            records.append({
                "mw": None, "logp": None, "hba": None, "hbd": None,
                "rotatable_bonds": None, "tpsa": None, "pains_flag": False,
                "admet_score": None
            })
            continue

        mol = row["_mol"]

        mw = Descriptors.MolWt(mol)
        logp = Crippen.MolLogP(mol)
        hba = Lipinski.NumHAcceptors(mol)
        hbd = Lipinski.NumHDonors(mol)
        rot = Lipinski.NumRotatableBonds(mol)
        tpsa = Descriptors.TPSA(mol)

        # PAINS filter
        try:
            pains_flag = catalog.HasMatch(mol)
        except Exception:
            pains_flag = False

        records.append({
            "mw": mw,
            "logp": logp,
            "hba": hba,
            "hbd": hbd,
            "rotatable_bonds": rot,
            "tpsa": tpsa,
            "pains_flag": pains_flag,
            "admet_score": 1.0  # start at 1, penalize
        })

    admet_df = pd.DataFrame(records)
    df = df.drop(columns=["_mol"]).join(admet_df)

    # Penalization function (0 = bad, 1 = good)
    for idx, row in df.iterrows():
        if row["admet_score"] is None:
            df.at[idx, "admet_score"] = 0.0
            continue

        score = 1.0

        # MW penalty: prefer < 900
        mw = row["mw"]
        if mw is not None:
            if mw > 900:
                score -= 0.3
            elif mw > 700:
                score -= 0.1

        # logP penalty: prefer < 6
        logp = row["logp"]
        if logp is not None:
            if logp > 6.0:
                score -= 0.2
            elif logp > 5.0:
                score -= 0.1

        # HBA penalty
        hba = row["hba"]
        if hba is not None and hba > 10:
            score -= 0.2

        # HBD penalty
        hbd = row["hbd"]
        if hbd is not None and hbd > 5:
            score -= 0.1

        # Rotatable bonds penalty
        rot = row["rotatable_bonds"]
        if rot is not None and rot > 15:
            score -= 0.1

        # PAINS penalty
        if row["pains_flag"]:
            score -= 0.3

        score = max(0.0, min(1.0, score))
        df.at[idx, "admet_score"] = score

    logger.info(f"ADMET scores computed. Valid compounds: {df['_valid_smiles'].sum()}")
    return df


def compute_combination_matrix(
    df: pd.DataFrame,
    cold_tumor_targets: list[str],
    admet_weight: float = 0.3
) -> dict:
    """Construye matriz N×M inhibidor × blanco."""

    all_targets = set()
    compound_targets = {}

    for _, row in df.iterrows():
        drug = row["drug_name"]
        targets_str = row.get("target_genes", "")
        if pd.isna(targets_str) or targets_str == "NA":
            compound_targets[drug] = []
            continue

        targets = [t.strip().upper() for t in str(targets_str).split(";")]
        targets = [t for t in targets if t]
        compound_targets[drug] = targets
        all_targets.update(targets)

    # Full target universe = cold tumor targets + compound targets
    target_universe = sorted(list(set(cold_tumor_targets) | all_targets))

    # Build matrix
    drug_list = sorted(compound_targets.keys())
    matrix = {}
    for drug in drug_list:
        targets = compound_targets.get(drug, [])
        row = {t: (1 if t in targets else 0) for t in target_universe}
        row["_admet_score"] = df[df["drug_name"] == drug]["admet_score"].values[0] \
            if drug in df["drug_name"].values else 0.0
        matrix[drug] = row

    matrix_meta = {
        "drugs": drug_list,
        "targets": target_universe,
        "matrix": matrix,
        "cold_tumor_targets": cold_tumor_targets
    }

    logger.info(f"Combination matrix: {len(drug_list)} drugs × {len(target_universe)} targets")
    return matrix_meta


def cluster_compounds(df: pd.DataFrame, n_clusters: int = 10) -> dict:
    """Reduce espacio via Butina clustering con Morgan fingerprints."""

    mols = {}
    valid_drugs = []

    for _, row in df.iterrows():
        if row["_valid_smiles"] != True:
            continue
        smiles = row["smiles"]
        if pd.isna(smiles) or smiles == "NA":
            continue
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            continue
        mols[row["drug_name"]] = mol
        valid_drugs.append(row["drug_name"])

    if len(mols) < 2:
        return {"clusters": {}, "representatives": list(mols.keys())}

    fps = [AllChem.GetMorganFingerprintAsBitVect(mols[drug], 2, nBits=2048) for drug in valid_drugs]

    # Butina clustering
    from rdkit.ML.Cluster import Butina
    nfps = len(fps)
    dists = []
    for i in range(1, nfps):
        sims = DataStructs.BulkDiceSimilarity(fps[i], fps[:i])
        for s in sims:
            dists.append(1.0 - s)

    # Flatten into cluster assignments (simplified Butina)
    cs = Butina.ClusterData(dists, nfps, distThresh=0.4, isDistData=True)

    cluster_dict = {drug: [] for drug in valid_drugs}
    for cid, cluster in enumerate(cs):
        for idx in cluster:
            cluster_dict[valid_drugs[idx]].append(cid)

    # Select representatives (first member of each cluster)
    representatives = [valid_drugs[cs[c][0]] for c in range(len(cs)) if cs[c]]

    return {
        "clusters": cluster_dict,
        "representatives": representatives,
        "n_clusters": len(cs)
    }


def run_combination_space_generator(
    config_path: str = None,
    compound_csv: str = None,
    output_dir: str = None
):
    """Main entry point for M3."""

    base_dir = Path(__file__).parent.parent
    config_path = config_path or str(base_dir / "config.yaml")
    compound_csv = compound_csv or str(base_dir / "data" / "compound_libraries" / "compound_library.csv")
    output_dir = output_dir or str(base_dir / "data" / "combination_space")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== M3: Combination Space Generator ===")

    # Load config
    config = load_config(config_path)
    admet_config = config.get("compound_library", {})
    cold_tumor_targets = config.get("cold_tumor_targets", [])

    # Load library
    df = load_compound_library(compound_csv)

    # Compute ADMET
    df = compute_admet_scores(df)

    # Save ADMET scores
    admet_output = output_dir / "admet_scores.csv"
    df[["drug_name", "chembl_id", "status", "mw", "logp", "hba", "hbd",
        "rotatable_bonds", "tpsa", "pains_flag", "admet_score"]].to_csv(admet_output, index=False)
    logger.info(f"ADMET scores saved to {admet_output}")

    # Build combination matrix
    matrix_meta = compute_combination_matrix(df, cold_tumor_targets)

    matrix_output = output_dir / "combination_matrix.json"
    with open(matrix_output, "w") as f:
        json.dump(matrix_meta, f, indent=2)
    logger.info(f"Combination matrix saved to {matrix_output}")

    # Cluster compounds
    df_valid = df[df["_valid_smiles"] == True].copy()
    cluster_results = cluster_compounds(df_valid)

    cluster_output = output_dir / "compound_clusters.json"
    with open(cluster_output, "w") as f:
        json.dump(cluster_results, f, indent=2)
    logger.info(f"Compound clusters saved to {cluster_output}")

    logger.info(f"=== M3 Complete: {len(matrix_meta['drugs'])} drugs × {len(matrix_meta['targets'])} targets ===")

    return matrix_meta


if __name__ == "__main__":
    result = run_combination_space_generator()
    print(json.dumps(result["drugs"], indent=2))
