"""
M1: Clasificador de Tumor Frío — GEMAGENTICDI
GEN-MAMA-MX · Capa 3: Matriz de Agentes Clínicos

Clasifica tumores como fríos/inmaduros basándose en:
- Score de exclusión inmune (TIL density, CD8A, FOXP3 ratio)
- Perfil TME: TGF-β, IDO1, ARG1, VEGFA, CCL2
- Subtipo: Claudin-low / Basal / Immune-excluded
"""

import json
import logging
import warnings
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore")


def load_config(config_path: str) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def compute_immune_signature_scores(
    df_expr: pd.DataFrame,
    gene_list: list[str],
    sample_col: str = "sample_id"
) -> pd.DataFrame:
    """Computa scores de expresión por gen para cada muestra."""

    available_genes = [g for g in gene_list if g in df_expr.columns]
    missing = set(gene_list) - set(available_genes)
    if missing:
        logger.warning(f"Genes not in expression matrix: {missing}")

    if not available_genes:
        return pd.DataFrame(columns=[sample_col] + gene_list)

    expr_subset = df_expr[[sample_col] + available_genes].copy()
    return expr_subset


def compute_cold_tumor_score(
    df_expr: pd.DataFrame,
    config: dict,
    sample_col: str = "sample_id"
) -> pd.DataFrame:
    """Calcula el cold tumor score compuesto."""

    thresholds = config.get("cold_tumor_thresholds", {})

    cd8a_low = thresholds.get("cd8a_low", 1.5)
    tgfbeta_high = thresholds.get("tgfbeta_high", 3.0)
    foxp3_ratio_high = thresholds.get("foxp3_ratio_high", 2.0)
    cold_min = thresholds.get("cold_tumor_min_score", 0.65)

    genes_tme = ["CD8A", "FOXP3", "TGFB1", "IDO1", "ARG1", "VEGFA", "CCL2"]
    available = [g for g in genes_tme if g in df_expr.columns]

    results = []
    for _, row in df_expr.iterrows():
        sample = row[sample_col]
        scores = {g: row[g] for g in available if g in row}

        # CD8A normalized (low = cold indicator)
        cd8a = scores.get("CD8A", 0.0)
        cd8a_norm = min(1.0, max(0.0, cd8a / cd8a_low)) if cd8a_low > 0 else 0.5

        # TGF-beta (high = cold indicator)
        tgf = scores.get("TGFB1", 0.0)
        tgf_high_flag = 1.0 if tgf >= tgfbeta_high else tgf / tgfbeta_high if tgfbeta_high > 0 else 0.0

        # IDO1 (high = cold indicator)
        ido1 = scores.get("IDO1", 0.0)
        ido1_high_flag = min(1.0, tgf / 2.0) if tgf > 0 else 0.0

        # FOXP3/CD8A ratio
        foxp3 = scores.get("FOXP3", 0.0)
        ratio = foxp3 / cd8a if cd8a > 0 else 0.0
        ratio_flag = min(1.0, ratio / foxp3_ratio_high) if foxp3_ratio_high > 0 else 0.0

        # Composite cold score
        cold_score = (
            0.30 * (1 - cd8a_norm) +
            0.30 * tgf_high_flag +
            0.20 * ido1_high_flag +
            0.20 * ratio_flag
        )

        # Classification
        if cold_score >= cold_min:
            classification = "Cold"
        elif cold_score >= 0.4:
            classification = "Warm"
        else:
            classification = "Hot"

        results.append({
            sample_col: sample,
            "cd8a_expr": cd8a,
            "foxp3_expr": foxp3,
            "tgfbeta_expr": tgf,
            "ido1_expr": ido1,
            "cd8a_norm": cd8a_norm,
            "tgfbeta_high_flag": tgf_high_flag,
            "ido1_high_flag": ido1_high_flag,
            "foxp3_cd8a_ratio": ratio,
            "ratio_flag": ratio_flag,
            "cold_score": cold_score,
            "classification": classification
        })

    return pd.DataFrame(results)


def assign_cold_subtype(
    df_scores: pd.DataFrame,
    sample_col: str = "sample_id"
) -> pd.DataFrame:
    """Asigna subtipo cold tumor: Claudin-low / Basal / Immune-excluded."""

    subtype_thresholds = {
        "Claudin-low": lambda r: (
            r.get("tgfbeta_high_flag", 0) > 0.6 and
            r.get("ido1_high_flag", 0) > 0.4 and
            r.get("cd8a_norm", 1) < 0.3
        ),
        "Basal": lambda r: (
            r.get("tgfbeta_high_flag", 0) > 0.3 and
            r.get("cd8a_norm", 1) < 0.5
        ),
        "Immune-excluded": lambda r: (
            r.get("ratio_flag", 0) > 0.5 and
            r.get("tgfbeta_high_flag", 0) > 0.4
        ),
    }

    def get_subtype(row):
        scores = row.to_dict()
        for subtype, condition in subtype_thresholds.items():
            if condition(scores):
                return subtype
        return "Claudin-low"  # default for cold tumors

    df_scores["cold_subtype"] = df_scores.apply(get_subtype, axis=1)
    return df_scores


def run_cold_tumor_classifier(
    config_path: str = None,
    expression_input: str = None,
    output_dir: str = None,
    gemamx_root: str = None,
    use_mock: bool = False
):
    """Main entry point for M1."""

    base_dir = Path(__file__).parent.parent
    config_path = config_path or str(base_dir / "config.yaml")
    output_dir = output_dir or str(base_dir / "outputs" / "cold_tumor_signatures")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== M1: Cold Tumor Classifier ===")

    # Load config
    config = load_config(config_path)

    # Load or create expression data
    if expression_input and Path(expression_input).exists():
        if expression_input.endswith(".tsv"):
            df_expr = pd.read_csv(expression_input, sep="\t")
        else:
            df_expr = pd.read_csv(expression_input)
        logger.info(f"Loaded expression data: {df_expr.shape}")
    else:
        # Check for Loki output as default real data
        loki_candidates = []
        # 1) Loki bundled under this repo (recommended)
        loki_candidates.append(base_dir / "tools" / "loki" / "outputs" / "predex" / "predex_slide_expression.tsv")
        # 2) Loki under an external GEMAMX root (if provided)
        if gemamx_root:
            loki_candidates.append(Path(gemamx_root) / "loki" / "outputs" / "predex" / "predex_slide_expression.tsv")
        # 3) GEO pre-processed TSV (output of scripts/prepare_geo_expression_for_m1.py)
        loki_candidates.append(base_dir / "data" / "m1_expression_input.tsv")

        loki_default = next((p for p in loki_candidates if p.exists()), None)
        if loki_default:
            logger.info(f"Using expression data from {loki_default}")
            df_expr = pd.read_csv(loki_default, sep="\t")
            if "slide_id" in df_expr.columns:
                df_expr = df_expr.rename(columns={"slide_id": "sample_id"})
        elif use_mock:
            logger.info("No expression data found — generating mock data for development")
            df_expr = generate_mock_expression_data(n_samples=50)
        else:
            raise FileNotFoundError(
                "No expression data found. Options:\n"
                "  1) Set GEMAGENTICDI_GEO_TSV to path of m1_expression_input.tsv\n"
                "  2) Run scripts/prepare_geo_expression_for_m1.py to generate data/m1_expression_input.tsv\n"
                "  3) Set GEMAGENTICDI_USE_MOCK=1 for development mode"
            )

    sample_col = "sample_id" if "sample_id" in df_expr.columns else df_expr.columns[0]

    # Compute signatures
    thresholds = config.get("cold_tumor_thresholds", {})
    genes_tme = thresholds.get("immunosuppressive_modules", []) + [
        "CD8A", "FOXP3", "TGFB1", "IDO1", "ARG1", "VEGFA", "CCL2"
    ]
    df_signatures = compute_immune_signature_scores(df_expr, genes_tme, sample_col)

    # Compute cold tumor score
    df_scores = compute_cold_tumor_score(df_expr, config, sample_col)

    # Assign subtype
    df_scores = assign_cold_subtype(df_scores, sample_col)

    # Merge signatures with scores
    df_output = df_signatures.merge(df_scores, on=sample_col)

    # Save outputs
    classification_output = base_dir / "outputs" / "cold_tumor_classification.csv"
    classification_output.parent.mkdir(parents=True, exist_ok=True)
    df_output.to_csv(classification_output, index=False)
    logger.info(f"Classification saved to {classification_output}")

    # Save signature scores JSON
    samples_data = df_output[[sample_col, "cold_score", "classification", "cold_subtype"]].to_dict("records")
    sig_dict = {
        "signatures": thresholds.get("immunosuppressive_modules", []),
        "samples": samples_data,
        "n_samples": len(samples_data)
    }

    sig_output = output_dir / "signature_scores.json"
    with open(sig_output, "w") as f:
        json.dump(sig_dict, f, indent=2)
    logger.info(f"Signature scores saved to {sig_output}")

    # Summary
    summary = df_output["classification"].value_counts().to_dict()
    logger.info(f"=== M1 Complete: {summary} ===")

    return df_output


def generate_mock_expression_data(n_samples: int = 50) -> pd.DataFrame:
    """Genera datos mock de expresión para desarrollo sin datos reales."""

    import numpy as np

    np.random.seed(42)
    samples = [f"SAMPLE_{i:03d}" for i in range(n_samples)]

    genes = [
        "CD8A", "FOXP3", "TGFB1", "TGFB2", "IDO1", "ARG1", "VEGFA", "CCL2",
        "CXCL8", "IL6", "MKI67", "ESR1", "PGR", "ERBB2", "EGFR", "PTEN"
    ]

    data = {"sample_id": samples}
    for gene in genes:
        if gene in ["CD8A", "FOXP3"]:
            # Low expression for CD8A/FOXP3 = cold tumors
            base = np.random.exponential(1.5, n_samples)
        elif gene in ["TGFB1", "TGFB2", "IDO1", "VEGFA"]:
            # High expression for immunosuppressive genes = cold
            base = np.random.exponential(3.0, n_samples)
        else:
            base = np.random.exponential(2.0, n_samples)

        data[gene] = np.round(base, 3)

    return pd.DataFrame(data)


if __name__ == "__main__":
    result = run_cold_tumor_classifier()
    print(f"Processed {len(result)} samples")
    print(result["classification"].value_counts())
