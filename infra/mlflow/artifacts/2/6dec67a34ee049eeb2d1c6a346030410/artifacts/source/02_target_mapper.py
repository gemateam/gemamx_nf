"""
M2: Mapa de Blancos Moleculares en Tumores Fríos — GEMAGENTICDI
GEN-MAMA-MX · Capa 3: Matriz de Agentes Clínicos

Construye la red PPI centrada en vías inmunosupresoras activas en tumores fríos,
identifica nodos hub y mapea a blancos druggables con inhibidores conocidos.
"""

import json
import logging
import warnings
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml
import networkx as nx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore")


# PPI stub curado para las 6 estrategias de rescate inmune
# Nodes: genes; Edges: interacciones proteína-proteína conocidas (STRING/BioGRID approximation)
STUB_PPI_NETWORK = {
    "nodes": [
        {"id": "TGFBR1", "type": "receptor", "strategy": "tgfbeta_reversal", "druggable": True},
        {"id": "TGFBR2", "type": "receptor", "strategy": "tgfbeta_reversal", "druggable": True},
        {"id": "PTK2", "type": "kinase", "strategy": "tgfbeta_reversal", "druggable": True},
        {"id": "KDR", "type": "receptor", "strategy": "tgfbeta_reversal", "druggable": True},
        {"id": "HAVCR2", "type": "checkpoint", "strategy": "alt_checkpoints", "druggable": True},
        {"id": "LAG3", "type": "checkpoint", "strategy": "alt_checkpoints", "druggable": True},
        {"id": "TIGIT", "type": "checkpoint", "strategy": "alt_checkpoints", "druggable": True},
        {"id": "VSIR", "type": "checkpoint", "strategy": "alt_checkpoints", "druggable": True},
        {"id": "SIGLEC15", "type": "checkpoint", "strategy": "alt_checkpoints", "druggable": True},
        {"id": "CSF1R", "type": "receptor", "strategy": "macrophage_repolarization", "druggable": True},
        {"id": "IDO1", "type": "enzyme", "strategy": "macrophage_repolarization", "druggable": True},
        {"id": "ARG1", "type": "enzyme", "strategy": "macrophage_repolarization", "druggable": True},
        {"id": "CD47", "type": "checkpoint", "strategy": "macrophage_repolarization", "druggable": True},
        {"id": "TMEM173", "type": " adaptor", "strategy": "sting_activation", "druggable": True},
        {"id": "CGAS", "type": "enzyme", "strategy": "sting_activation", "druggable": True},
        {"id": "TLR9", "type": "receptor", "strategy": "sting_activation", "druggable": True},
        {"id": "NLRP3", "type": "inflammasome", "strategy": "sting_activation", "druggable": True},
        {"id": "TDO2", "type": "enzyme", "strategy": "metabolic_modulation", "druggable": True},
        {"id": "ADORA2A", "type": "receptor", "strategy": "metabolic_modulation", "druggable": True},
        {"id": "LDHA", "type": "enzyme", "strategy": "metabolic_modulation", "druggable": True},
        {"id": "PARP1", "type": "enzyme", "strategy": "parp_chemo_immuno", "druggable": True},
        {"id": "PARP2", "type": "enzyme", "strategy": "parp_chemo_immuno", "druggable": True},
        {"id": "TOP2A", "type": "enzyme", "strategy": "parp_chemo_immuno", "druggable": True},
        {"id": "DNMT1", "type": "enzyme", "strategy": "parp_chemo_immuno", "druggable": True},
        {"id": "NFKB1", "type": "transcription_factor", "strategy": "sting_activation", "druggable": False},
        {"id": "SIRT1", "type": "enzyme", "strategy": "metabolic_modulation", "druggable": False},
    ],
    "edges": [
        # TGF-β signaling
        {"source": "TGFBR1", "target": "TGFBR2", "weight": 0.95, "direction": "TGFBR1->TGFBR2"},
        {"source": "TGFBR2", "target": "SMAD2", "weight": 0.90, "direction": "TGFBR2->SMAD2"},
        {"source": "TGFBR2", "target": "PTK2", "weight": 0.70, "direction": "TGFBR2->PTK2"},
        {"source": "PTK2", "target": "SRC", "weight": 0.80, "direction": "PTK2->SRC"},
        {"source": "KDR", "target": "VEGFA", "weight": 0.85, "direction": "KDR->VEGFA"},
        {"source": "VEGFA", "target": "NFKB1", "weight": 0.60, "direction": "VEGFA->NFKB1"},
        # Alternative checkpoints
        {"source": "HAVCR2", "target": "LGALS9", "weight": 0.75, "direction": "HAVCR2->LGALS9"},
        {"source": "TIGIT", "target": "PVR", "weight": 0.90, "direction": "TIGIT->PVR"},
        {"source": "LAG3", "target": "MHC2", "weight": 0.80, "direction": "LAG3->MHC2"},
        {"source": "SIGLEC15", "target": "CD33", "weight": 0.65, "direction": "SIGLEC15->CD33"},
        # Macrophage repolarization
        {"source": "CSF1R", "target": "CSF1", "weight": 0.85, "direction": "CSF1R->CSF1"},
        {"source": "IDO1", "target": "KYNU", "weight": 0.75, "direction": "IDO1->KYNU"},
        {"source": "ARG1", "target": "ARG2", "weight": 0.70, "direction": "ARG1->ARG2"},
        {"source": "CD47", "target": "SIRPA", "weight": 0.95, "direction": "CD47->SIRPA"},
        # STING activation
        {"source": "CGAS", "target": "STING1", "weight": 0.88, "direction": "CGAS->STING1"},
        {"source": "STING1", "target": "TBK1", "weight": 0.90, "direction": "STING1->TBK1"},
        {"source": "STING1", "target": "NFKB1", "weight": 0.75, "direction": "STING1->NFKB1"},
        {"source": "TLR9", "target": "MYD88", "weight": 0.85, "direction": "TLR9->MYD88"},
        {"source": "NLRP3", "target": "ASC", "weight": 0.80, "direction": "NLRP3->ASC"},
        # Metabolic modulation
        {"source": "TDO2", "target": "KYNU", "weight": 0.70, "direction": "TDO2->KYNU"},
        {"source": "IDO1", "target": "TDO2", "weight": 0.65, "direction": "IDO1->TDO2"},
        {"source": "ADORA2A", "target": "ATP", "weight": 0.60, "direction": "ADORA2A->ATP"},
        {"source": "LDHA", "target": "LDHB", "weight": 0.90, "direction": "LDHA->LDHB"},
        {"source": "LDHA", "target": "NAD", "weight": 0.75, "direction": "LDHA->NAD"},
        # PARP/chemo
        {"source": "PARP1", "target": "NAD", "weight": 0.80, "direction": "PARP1->NAD"},
        {"source": "PARP2", "target": "NAD", "weight": 0.75, "direction": "PARP2->NAD"},
        {"source": "TOP2A", "target": "DNA", "weight": 0.85, "direction": "TOP2A->DNA"},
        {"source": "DNMT1", "target": "DNA", "weight": 0.80, "direction": "DNMT1->DNA"},
        {"source": "PARP1", "target": "TOP2A", "weight": 0.60, "direction": "PARP1->TOP2A"},
        # Cross-strategy interactions
        {"source": "NFKB1", "target": "IDO1", "weight": 0.65, "direction": "NFKB1->IDO1"},
        {"source": "SIRT1", "target": "LDHA", "weight": 0.60, "direction": "SIRT1->LDHA"},
        {"source": "SIRT1", "target": "PARP1", "weight": 0.55, "direction": "SIRT1->PARP1"},
    ]
}


def load_config(config_path: str) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def build_ppi_graph(ppi_data: dict) -> nx.DiGraph:
    """Construye grafo NetworkX desde datos PPI."""

    G = nx.DiGraph()

    for node in ppi_data["nodes"]:
        G.add_node(node["id"], **node)

    for edge in ppi_data["edges"]:
        G.add_edge(edge["source"], edge["target"], **edge)

    logger.info(f"PPI graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    return G


def compute_hub_scores(G: nx.DiGraph) -> pd.DataFrame:
    """Calcula centrality scores para identificar nodos hub."""

    degree_c = nx.degree_centrality(G)
    betweenness_c = nx.betweenness_centrality(G)
    in_degree_c = nx.in_degree_centrality(G)
    out_degree_c = nx.out_degree_centrality(G)

    # PageRank as additional hub signal
    pagerank = nx.pagerank(G)

    hub_data = []
    for node in G.nodes():
        hub_data.append({
            "gene": node,
            "strategy": G.nodes[node].get("strategy", "unknown"),
            "druggable": G.nodes[node].get("druggable", False),
            "node_type": G.nodes[node].get("type", "unknown"),
            "degree_centrality": degree_c.get(node, 0),
            "betweenness_centrality": betweenness_c.get(node, 0),
            "in_degree_centrality": in_degree_c.get(node, 0),
            "out_degree_centrality": out_degree_c.get(node, 0),
            "pagerank": pagerank.get(node, 0),
            "total_degree": G.degree(node)
        })

    df_hubs = pd.DataFrame(hub_data)

    # Composite hub score
    df_hubs["hub_score"] = (
        0.30 * df_hubs["degree_centrality"] +
        0.30 * df_hubs["betweenness_centrality"] +
        0.20 * df_hubs["pagerank"] +
        0.20 * df_hubs["druggable"].astype(float)
    )

    df_hubs = df_hubs.sort_values("hub_score", ascending=False)
    return df_hubs


def map_druggable_targets(
    df_hubs: pd.DataFrame,
    combination_matrix: dict
) -> pd.DataFrame:
    """Filtra blancos druggables y mapea compuestos que los atacan."""

    df_druggable = df_hubs[df_hubs["druggable"] == True].copy()

    drugs = combination_matrix.get("drugs", [])
    targets = combination_matrix.get("targets", [])
    matrix = combination_matrix.get("matrix", {})

    # For each druggable target, find which drugs hit it
    drug_target_map = {}
    for drug in drugs:
        drug_row = matrix.get(drug, {})
        hit_targets = [t for t in targets if drug_row.get(t, 0) == 1]
        for t in hit_targets:
            if t not in drug_target_map:
                drug_target_map[t] = []
            drug_target_map[t].append(drug)

    results = []
    for _, row in df_druggable.iterrows():
        gene = row["gene"]
        drugs_hit = drug_target_map.get(gene, [])
        results.append({
            "gene": gene,
            "strategy": row["strategy"],
            "hub_score": row["hub_score"],
            "druggable_drugs": drugs_hit,
            "n_drugs": len(drugs_hit)
        })

    df_druggable_targets = pd.DataFrame(results)
    logger.info(f"Druggable targets with known inhibitors: {len(df_druggable_targets)}")
    return df_druggable_targets


def run_target_mapper(
    config_path: str = None,
    combination_matrix_json: str = None,
    output_dir: str = None
):
    """Main entry point for M2."""

    base_dir = Path(__file__).parent.parent
    config_path = config_path or str(base_dir / "config.yaml")
    output_dir = output_dir or str(base_dir / "data" / "target_mapping")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== M2: Target PPI Mapper ===")

    # Build PPI graph from stub
    G = build_ppi_graph(STUB_PPI_NETWORK)

    # Compute hub scores
    df_hubs = compute_hub_scores(G)

    hub_output = output_dir / "hub_targets.json"
    hub_records = df_hubs.to_dict("records")
    with open(hub_output, "w") as f:
        json.dump(hub_records, f, indent=2)
    logger.info(f"Hub targets saved to {hub_output}")

    # Load combination matrix if available
    if combination_matrix_json and Path(combination_matrix_json).exists():
        with open(combination_matrix_json) as f:
            combination_matrix = json.load(f)
    else:
        matrix_path = base_dir / "data" / "combination_space" / "combination_matrix.json"
        if matrix_path.exists():
            with open(matrix_path) as f:
                combination_matrix = json.load(f)
        else:
            logger.warning("No combination matrix found — skipping druggable mapping")
            combination_matrix = {"drugs": [], "targets": [], "matrix": {}}

    # Map druggable targets
    df_druggable = map_druggable_targets(df_hubs, combination_matrix)

    druggable_output = output_dir / "druggable_targets.json"
    with open(druggable_output, "w") as f:
        json.dump(df_druggable.to_dict("records"), f, indent=2)
    logger.info(f"Druggable targets saved to {druggable_output}")

    # Save coverage matrix
    drugs = combination_matrix.get("drugs", [])
    targets = combination_matrix.get("targets", [])
    matrix = combination_matrix.get("matrix", {})

    target_coverage = {}
    for target in targets:
        drugs_hit = [d for d in drugs if matrix.get(d, {}).get(target, 0) == 1]
        target_coverage[target] = {
            "covered": len(drugs_hit) > 0,
            "drugs": drugs_hit,
            "n_drugs": len(drugs_hit)
        }

    coverage_output = output_dir / "target_coverage.json"
    with open(coverage_output, "w") as f:
        json.dump(target_coverage, f, indent=2)
    logger.info(f"Target coverage saved to {coverage_output}")

    # PPI network full export
    ppi_output = output_dir / "ppi_network.json"
    with open(ppi_output, "w") as f:
        json.dump(STUB_PPI_NETWORK, f, indent=2)
    logger.info(f"PPI network saved to {ppi_output}")

    logger.info(f"=== M2 Complete: {len(df_hubs)} targets, {len(df_druggable)} druggable ===")

    return {
        "hub_targets": hub_records,
        "druggable_targets": df_druggable.to_dict("records"),
        "target_coverage": target_coverage
    }


if __name__ == "__main__":
    result = run_target_mapper()
    print(json.dumps(result["druggable_targets"][:5], indent=2))
