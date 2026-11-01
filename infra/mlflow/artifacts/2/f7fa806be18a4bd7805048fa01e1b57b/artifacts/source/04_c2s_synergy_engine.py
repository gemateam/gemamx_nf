"""
M4: Motor de Sinergias C2S-Scale — GEMAGENTICDI
GEN-MAMA-MX · Capa 3: Matriz de Agentes Clínicos

Calcula el score C2S-Scale multidimensional para cada combinación candidata:
- C1: Cobertura de blancos inmuno-evasivos
- C2: Sinergia molecular predicha (Bliss Independence)
- C3: Seguridad/toxicidad ADMET
- C4: Novedad vs literatura
- C5: Viabilidad clínica (acceso MX)
"""

import json
import logging
import warnings
from pathlib import Path
from typing import Optional, Tuple
from itertools import combinations

import pandas as pd
import yaml
import numpy as np
import networkx as nx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore")


def load_config(config_path: str) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def load_mx_access_registry(json_path: str) -> dict:
    """Carga registro de acceso a medicamentos en México."""
    if not json_path or not str(json_path).strip():
        return {}
    if Path(json_path).exists():
        with open(json_path) as f:
            return json.load(f)
    return {}


def compute_bliss_independence(
    efficacy_a: float,
    efficacy_b: float,
    efficacy_c: float = 0.0
) -> Tuple[float, float]:
    """
    Calcula Bliss excess para combinación de dos o tres agentes.
    E_bliss = E_A + E_B + E_C - E_A*E_B - E_A*E_C - E_B*E_C + E_A*E_B*E_C
    Bliss excess = E_observed - E_bliss
    Returns: (bliss_excess, bliss_expected)
    """
    # Normalize efficacy to [0,1]
    e_a = max(0.0, min(1.0, efficacy_a))
    e_b = max(0.0, min(1.0, efficacy_b))
    e_c = max(0.0, min(1.0, efficacy_c))

    if e_c > 0:
        e_bliss = e_a + e_b + e_c - e_a*e_b - e_a*e_c - e_b*e_c + e_a*e_b*e_c
    else:
        e_bliss = e_a + e_b - e_a * e_b

    # For synergistic: observed > bliss (excess > 0)
    return e_bliss, e_bliss


def compute_c1_immune_coverage(
    drug_a: str,
    drug_b: str,
    combination_matrix: dict,
    cold_tumor_targets: list[str]
) -> float:
    """C1: Fraction of cold tumor targets hit by the drug pair."""
    targets = combination_matrix.get("targets", [])
    matrix = combination_matrix.get("matrix", {})

    targets_a = set()
    targets_b = set()

    if drug_a in matrix:
        row_a = matrix[drug_a]
        targets_a = {t for t in targets if row_a.get(t, 0) == 1}

    if drug_b in matrix:
        row_b = matrix[drug_b]
        targets_b = {t for t in targets if row_b.get(t, 0) == 1}

    union_targets = targets_a | targets_b
    covered = union_targets & set(cold_tumor_targets)

    # Scale coverage: hitting 8 targets (1/3 of cold targets) is considered 100% for a pair
    coverage_scaled = (len(covered) / 8.0) 
    return min(1.0, coverage_scaled)


def compute_c2_synergy_score(
    drug_a: str,
    drug_b: str,
    efficacy_map: dict,
    combination_matrix: dict,
    ppi_graph: nx.DiGraph = None
) -> float:
    """
    C2: Sinergia predicha via Bliss Independence y Network Distance.
    - Sinergia mayor si los blancos están a distancia < 3 en la red PPI.
    - Sinergia máxima si actúan en la misma vía pero diferentes genes.
    """
    e_a = efficacy_map.get(drug_a, 0.5)
    e_b = efficacy_map.get(drug_b, 0.5)

    synergy_bonus = 0.0
    if ppi_graph:
        matrix = combination_matrix.get("matrix", {})
        targets_a = [t for t, v in matrix.get(drug_a, {}).items() if v == 1 and not t.startswith("_")]
        targets_b = [t for t, v in matrix.get(drug_b, {}).items() if v == 1 and not t.startswith("_")]

        # Calculate min distance between any target of A and any target of B
        min_dist = 999
        for ta in targets_a:
            for tb in targets_b:
                if ta == tb: 
                    min_dist = min(min_dist, 0)
                    continue
                try:
                    if ppi_graph.has_node(ta) and ppi_graph.has_node(tb):
                        dist = nx.shortest_path_length(ppi_graph.to_undirected(), ta, tb)
                        min_dist = min(min_dist, dist)
                except nx.NetworkXNoPath:
                    pass
        
        if min_dist == 0:
            synergy_bonus = 0.05  # redundancy
        elif min_dist == 1:
            synergy_bonus = 0.25  # direct interaction
        elif min_dist == 2:
            synergy_bonus = 0.20  # nearby
        elif min_dist == 3:
            synergy_bonus = 0.10
            
    # Add strategy bonus
    matrix = combination_matrix.get("matrix", {})
    strat_a = matrix.get(drug_a, {}).get("_strategy")
    strat_b = matrix.get(drug_b, {}).get("_strategy")
    if strat_a and strat_b and strat_a != strat_b:
        # Cross-pathway inhibition is often more synergistic in cold tumors
        synergy_bonus += 0.15
    
    e_obs = 0.5 + synergy_bonus # Base 0.5 observed efficacy + bonus
    
    e_bliss, _ = compute_bliss_independence(e_a, e_b)
    bliss_excess = e_obs - e_bliss

    # Normalize to [0,1]
    synergy_score = (bliss_excess + 0.5) / 1.0
    return max(0.0, min(1.0, synergy_score))


def compute_c3_safety_score(
    drug_a: str,
    drug_b: str,
    admet_df: pd.DataFrame
) -> float:
    """C3: Inverse of ADMET penalty (safety score)."""
    scores = []
    for drug in [drug_a, drug_b]:
        row = admet_df[admet_df["drug_name"] == drug]
        if len(row) > 0:
            score = row["admet_score"].values[0]
            scores.append(score if score is not None else 0.0)
        else:
            scores.append(0.5)  # default

    # Use minimum of the two (safety = weakest link)
    safety = min(scores)
    return safety


def compute_c4_novelty_score(
    drug_a: str,
    drug_b: str,
    existing_combinations: set
) -> float:
    """
    C4: Novedad = 1 - max_similarity vs combinaciones publicadas.
    Stub: 1.0 para combinaciones no en librería existente, 0.5 para conocidas.
    """
    combo_key = frozenset([drug_a.lower(), drug_b.lower()])
    if combo_key in existing_combinations:
        return 0.3  # known combination
    return 1.0  # novel


def compute_c5_clinical_feasibility(
    drug_a: str,
    drug_b: str,
    mx_registry: dict
) -> float:
    """C5: Clinical feasibility based on Mexico drug access registry."""
    drugs_status = mx_registry.get("drugs", {})

    scores = []
    for drug in [drug_a, drug_b]:
        drug_lower = drug.lower()
        found = False
        for name, info in drugs_status.items():
            if drug_lower in name.lower():
                sgmm = info.get("sgmm_estimate", "unknown")
                if sgmm == "high":
                    scores.append(0.9)
                elif sgmm == "medium":
                    scores.append(0.6)
                elif sgmm == "low":
                    scores.append(0.3)
                else:
                    scores.append(0.5)
                found = True
                break
        if not found:
            scores.append(0.4)  # unknown = moderate

    # Average of both drugs
    feasibility = sum(scores) / len(scores) if scores else 0.4
    return feasibility


def compute_c2s_score(
    c1: float,
    c2: float,
    c3: float,
    c4: float,
    c5: float,
    weights: dict
) -> float:
    """Calcula C2S-Scale score ponderado."""

    score = (
        weights.get("C1_immune_coverage", 0.25) * c1 +
        weights.get("C2_synergy_score", 0.25) * c2 +
        weights.get("C3_safety_score", 0.20) * c3 +
        weights.get("C4_novelty_score", 0.20) * c4 +
        weights.get("C5_clinical_feasibility", 0.10) * c5
    ) * 100

    return score


def classify_tier(score: float, thresholds: dict) -> int:
    """Clasifica combinación en Tier según score."""
    if score >= thresholds.get("tier1_min", 80):
        return 1
    elif score >= thresholds.get("tier2_min", 60):
        return 2
    elif score >= thresholds.get("tier3_min", 40):
        return 3
    else:
        return 0  # Discarded


def generate_combination_id(index: int) -> str:
    """Genera ID único para combinación."""
    return f"C2S-MX-{index:04d}"


def evaluate_all_pairs(
    compound_library_df: pd.DataFrame,
    combination_matrix: dict,
    admet_df: pd.DataFrame,
    mx_registry: dict,
    config: dict,
    cold_tumor_targets: list[str],
    ppi_graph: nx.DiGraph = None
) -> list[dict]:
    """Evalúa todas las parejas de compuestos."""

    weights = config.get("c2s_weights", {})
    thresholds = config.get("tier_thresholds", {})
    strategies = config.get("immune_rescue_strategies", {})

    # Map drugs to strategies
    drug_strategy_map = {}
    for _, row in compound_library_df.iterrows():
        drug_strategy_map[row["drug_name"]] = row.get("strategy", "unknown")

    # Known drug combinations from existing GEMAMX docking library
    existing_combos = {
        frozenset(["abemaciclib", "alpelisib"]),
        frozenset(["palbociclib", "alpelisib"]),
        frozenset(["ribociclib", "alpelisib"]),
    }

    # Efficacy proxy map (from ADMET and target coverage)
    efficacy_map = {}
    for _, row in admet_df.iterrows():
        drug = row["drug_name"]
        admet = row["admet_score"]
        if admet is not None:
            # Higher ADMET score = more druggable = higher efficacy proxy
            efficacy_map[drug] = admet

    drugs = combination_matrix.get("drugs", [])
    results = []

    combo_idx = 1
    for drug_a, drug_b in combinations(drugs, 2):
        # C1: Immune coverage
        c1 = compute_c1_immune_coverage(
            drug_a, drug_b, combination_matrix, cold_tumor_targets
        )

        # C2: Synergy
        stra_a = drug_strategy_map.get(drug_a, "unknown")
        stra_b = drug_strategy_map.get(drug_b, "unknown")
        c2 = compute_c2_synergy_score(
            drug_a, drug_b, efficacy_map, combination_matrix, ppi_graph
        )

        strategy_combo = f"{stra_a} + {stra_b}"
        c3 = compute_c3_safety_score(drug_a, drug_b, admet_df)

        # C4: Novelty
        c4 = compute_c4_novelty_score(drug_a, drug_b, existing_combos)

        # C5: Clinical feasibility
        c5 = compute_c5_clinical_feasibility(drug_a, drug_b, mx_registry)

        # C2S Score
        c2s_score = compute_c2s_score(c1, c2, c3, c4, c5, weights)

        # Tier
        tier = classify_tier(c2s_score, thresholds)

        # Strategy combination
        strategy_combo = f"{stra_a} + {stra_b}"

        results.append({
            "combination_id": generate_combination_id(combo_idx),
            "drug_a": drug_a,
            "drug_b": drug_b,
            "third_agent": None,
            "target_strategy": strategy_combo,
            "cold_tumor_subtype": "Claudin-low / Immune-excluded",
            "c2s_score": round(c2s_score, 1),
            "tier": tier,
            "components": {
                "C1_immune_coverage": round(c1, 3),
                "C2_synergy_score": round(c2, 3),
                "C3_safety_score": round(c3, 3),
                "C4_novelty_score": round(c4, 3),
                "C5_clinical_feasibility": round(c5, 3)
            },
            "novelty_statement": f"Combinación {drug_a} + {drug_b} — {strategy_combo}",
            "docking_results": {},
            "experimental_roadmap": [
                f"Validación sinergia: líneas TNBC frías (MDA-MB-231, HS578T)",
                f"Evaluación {drug_a} + {drug_b} en cocultivo tumor-PBMC",
                "Modelo murino: 4T1 cold variant — supervivencia + infiltrado inmune"
            ],
            "references_similar": [],
            "generated_by": "GEMAGENTICDI v1.0 — GEN-MAMA-MX C2S-Scale"
        })

        combo_idx += 1

    return results


def run_c2s_synergy_engine(
    config_path: str = None,
    compound_csv: str = None,
    combination_matrix_json: str = None,
    admet_csv: str = None,
    mx_registry_json: str = None,
    ppi_network_json: str = None,
    output_dir: str = None
):
    """Main entry point for M4."""

    base_dir = Path(__file__).parent.parent
    config_path = config_path or str(base_dir / "config.yaml")
    compound_csv = compound_csv or str(base_dir / "data" / "compound_libraries" / "compound_library.csv")
    combination_matrix_json = combination_matrix_json or str(base_dir / "data" / "combination_space" / "combination_matrix.json")
    admet_csv = admet_csv or str(base_dir / "data" / "combination_space" / "admet_scores.csv")
    mx_registry_json = mx_registry_json or str(base_dir / ".." / "mx_access_registry.json")
    ppi_network_json = ppi_network_json or str(base_dir / "data" / "target_mapping" / "ppi_network.json")
    output_dir = output_dir or str(base_dir / "outputs")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates_dir = output_dir / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== M4: C2S Synergy Engine ===")

    # Load config
    config = load_config(config_path)
    cold_tumor_targets = config.get("cold_tumor_targets", [])

    # Load data
    compound_df = pd.read_csv(compound_csv)

    # Load or create ADMET scores
    if Path(admet_csv).exists():
        admet_df = pd.read_csv(admet_csv)
    else:
        logger.warning(f"ADMET CSV not found: {admet_csv} — computing inline")
        admet_df = compound_df.copy()
        admet_df["admet_score"] = 0.7  # default score when RDKit unavailable
        admet_df["_valid_smiles"] = admet_df["smiles"].notna() & (admet_df["smiles"] != "NA")

    if Path(combination_matrix_json).exists():
        with open(combination_matrix_json) as f:
            combination_matrix = json.load(f)
    else:
        logger.warning(f"Combination matrix not found: {combination_matrix_json} — generating inline")
        drugs = compound_df["drug_name"].tolist()
        all_targets = set(cold_tumor_targets)
        for targets_str in compound_df["target_genes"].dropna():
            for t in str(targets_str).split(";"):
                t = t.strip()
                if t:
                    all_targets.add(t)
        targets = list(all_targets)
        matrix = {}
        for d in drugs:
            drug_row = compound_df[compound_df["drug_name"] == d]
            drug_targets_list = str(drug_row["target_genes"].values[0]).split(";") if len(drug_row) > 0 else []
            drug_targets_set = {t.strip() for t in drug_targets_list}
            matrix[d] = {t: (1 if t in drug_targets_set else 0) for t in targets}
        combination_matrix = {"drugs": drugs, "targets": targets, "matrix": matrix, "cold_tumor_targets": cold_tumor_targets}

    mx_registry = load_mx_access_registry(mx_registry_json)

    # Load PPI graph
    ppi_graph = None
    if Path(ppi_network_json).exists():
        try:
            with open(ppi_network_json) as f:
                ppi_data = json.load(f)
            ppi_graph = nx.DiGraph()
            for node in ppi_data.get("nodes", []):
                ppi_graph.add_node(node["id"], **node)
            for edge in ppi_data.get("edges", []):
                ppi_graph.add_edge(edge["source"], edge["target"], **edge)
            logger.info(f"Loaded PPI graph: {ppi_graph.number_of_nodes()} nodes")
        except Exception as e:
            logger.warning(f"Failed to load PPI graph: {e}")

    # Evaluate all pairs
    all_results = evaluate_all_pairs(
        compound_df,
        combination_matrix,
        admet_df,
        mx_registry,
        config,
        cold_tumor_targets,
        ppi_graph
    )

    # Sort by C2S score
    all_results.sort(key=lambda x: x["c2s_score"], reverse=True)

    # Save full results
    full_output = output_dir / "synergy_maps" / "c2s_scores_full.json"
    full_output.parent.mkdir(parents=True, exist_ok=True)
    with open(full_output, "w") as f:
        json.dump(all_results, f, indent=2)
    logger.info(f"Full C2S scores saved to {full_output}")

    # Separate by tier

    # Save Tier-specific results
    tier1 = [r for r in all_results if r.get("tier") == 1]
    tier2 = [r for r in all_results if r.get("tier") == 2]
    tier3 = [r for r in all_results if r.get("tier") == 3]

    with open(candidates_dir / "tier1_candidates.json", "w") as f:
        json.dump(tier1, f, indent=2)
    with open(candidates_dir / "tier2_candidates.json", "w") as f:
        json.dump(tier2, f, indent=2)

    logger.info(f"Tier 1 candidates: {len(tier1)}")
    logger.info(f"Tier 2 candidates: {len(tier2)}")

    logger.info(f"=== M4 Complete: {len(all_results)} combinations evaluated ===")

    return {
        "full_results": all_results,
        "tier1": tier1,
        "tier2": tier2,
        "tier3": tier3
    }


if __name__ == "__main__":
    result = run_c2s_synergy_engine()
    print(f"Tier 1: {len(result['tier1'])}")
    print(f"Tier 2: {len(result['tier2'])}")
    print(f"Tier 3: {len(result['tier3'])}")
    if result["tier1"]:
        top = result["tier1"][0]
        print(f"Top candidate: {top['combination_id']} — C2S={top['c2s_score']}")
