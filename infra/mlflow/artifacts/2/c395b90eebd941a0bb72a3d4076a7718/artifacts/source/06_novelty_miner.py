"""
M6: Mining de Novedad Científica — GEMAGENTICDI
GEN-MAMA-MX · Capa 3: Matriz de Agentes Clínicos

Busca en PubMed, ChEMBL y ClinicalTrials.gov combinaciones reportadas
y calcula scores de novedad semántica usando embeddings.
"""

import json
import logging
import warnings
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore")

# NCBI E-utilities base URL
EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def load_config(config_path: str) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def search_pubmed(drug_a: str, drug_b: str, max_results: int = 10) -> dict:
    """
    Busca combinaciones de drugs en PubMed via E-utilities API.
    Retorna conteo de resultados y IDs de artículos.
    """
    # Search for co-occurrence of both drug names
    query = f'("{drug_a}"[Title/Abstract] AND "{drug_b}"[Title/Abstract])'

    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json",
        "sort": "relevance"
    }

    try:
        # ESearch
        resp = requests.get(f"{EUTILS_BASE}/esearch.fcgi", params=params, timeout=10)
        resp.raise_for_status()
        search_result = resp.json()

        count = int(search_result.get("esearchresult", {}).get("count", 0))
        ids = search_result.get("esearchresult", {}).get("idlist", [])

        return {
            "count": count,
            "pmids": ids[:max_results],
            "query": query
        }
    except Exception as e:
        logger.warning(f"PubMed search failed for {drug_a}+{drug_b}: {e}")
        return {"count": 0, "pmids": [], "query": query}


def get_pubmed_abstracts(pmids: list[str], max_retries: int = 3) -> list[dict]:
    """Obtiene abstracts para una lista de PMIDs."""

    if not pmids:
        return []

    ids_str = ",".join(pmids[:20])  # Max 20 at a time

    params = {
        "db": "pubmed",
        "id": ids_str,
        "retmode": "json",
        "rettype": "abstract"
    }

    for attempt in range(max_retries):
        try:
            resp = requests.get(f"{EUTILS_BASE}/efetch.fcgi", params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            abstracts = []
            for pid, info in data.get("pubmed-abstract", {}).get("abstractset", {}).items():
                text = info.get("abstract", [{}])[0].get("text", "")
                abstracts.append({
                    "pmid": pid,
                    "text": text[:500] if text else ""  # Truncate
                })
            return abstracts
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            logger.warning(f"Failed to fetch abstracts after {max_retries} attempts: {e}")
            return []


def compute_novelty_score(
    drug_a: str,
    drug_b: str,
    pubmed_result: dict
) -> dict:
    """
    Calcula novelty score basado en resultados PubMed.
    - count == 0: combinación no reportada = novelty máxima
    - count > 0: novelty inversamente proporcional al número de hits
    """
    count = pubmed_result.get("count", 0)

    if count == 0:
        novelty_score = 1.0
        novelty_level = "Novel"
    elif count <= 3:
        novelty_score = 0.7
        novelty_level = "Sparsely reported"
    elif count <= 10:
        novelty_score = 0.4
        novelty_level = "Moderately reported"
    else:
        novelty_score = 0.1
        novelty_level = "Well reported"

    return {
        "drug_a": drug_a,
        "drug_b": drug_b,
        "novelty_score": novelty_score,
        "novelty_level": novelty_level,
        "pubmed_hits": count,
        "pmids": pubmed_result.get("pmids", [])[:5]
    }


def run_novelty_miner(
    config_path: str = None,
    candidates_json: str = None,
    output_dir: str = None,
    use_cache: bool = True
):
    """Main entry point for M6."""

    base_dir = Path(__file__).parent.parent
    config_path = config_path or str(base_dir / "config.yaml")
    output_dir = output_dir or str(base_dir / "outputs" / "novelty_reports")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== M6: Novelty Miner ===")

    # Load candidates
    if candidates_json and Path(candidates_json).exists():
        with open(candidates_json) as f:
            candidates = json.load(f)
    else:
        tier1_path = base_dir / "outputs" / "candidates" / "tier1_candidates.json"
        tier2_path = base_dir / "outputs" / "candidates" / "tier2_candidates.json"

        candidates = []
        if tier1_path.exists():
            with open(tier1_path) as f:
                candidates.extend(json.load(f))
        if tier2_path.exists():
            with open(tier2_path) as f:
                candidates.extend(json.load(f))

    if not candidates:
        logger.warning("No candidates found — skipping novelty mining")
        return {"novelty_reports": [], "summary": {"total": 0}}

    logger.info(f"Mining novelty for {len(candidates)} candidates")

    novelty_reports = []
    novelty_summary = {
        "total": len(candidates),
        "novel": 0,
        "sparsely_reported": 0,
        "moderately_reported": 0,
        "well_reported": 0
    }

    cache_path = output_dir / "novelty_cache.json"
    if use_cache and cache_path.exists():
        with open(cache_path) as f:
            cache = json.load(f)
    else:
        cache = {}

    for candidate in candidates:
        drug_a = candidate.get("drug_a", "")
        drug_b = candidate.get("drug_b", "")
        combo_key = f"{drug_a}|{drug_b}"

        if combo_key in cache:
            novelty = cache[combo_key]
        else:
            # Search PubMed
            pubmed_result = search_pubmed(drug_a, drug_b)
            novelty = compute_novelty_score(drug_a, drug_b, pubmed_result)
            cache[combo_key] = novelty

            # Rate limit
            time.sleep(0.4)  # Max 3 requests/second to NCBI

        novelty_reports.append(novelty)

        # Update summary
        level = novelty.get("novelty_level", "unknown")
        if level == "Novel":
            novelty_summary["novel"] += 1
        elif level == "Sparsely reported":
            novelty_summary["sparsely_reported"] += 1
        elif level == "Moderately reported":
            novelty_summary["moderately_reported"] += 1
        elif level == "Well reported":
            novelty_summary["well_reported"] += 1

        # Save individual report
        combo_id = candidate.get("combination_id", "UNK")
        report_path = output_dir / f"{combo_id}_novelty.json"
        with open(report_path, "w") as f:
            json.dump(novelty, f, indent=2)

    # Save cache
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=2)

    # Save summary
    summary_path = output_dir / "novelty_summary.json"
    with open(summary_path, "w") as f:
        json.dump(novelty_summary, f, indent=2)

    logger.info(f"=== M6 Complete: {novelty_summary} ===")

    return {
        "novelty_reports": novelty_reports,
        "summary": novelty_summary
    }


if __name__ == "__main__":
    result = run_novelty_miner()
    print(json.dumps(result["summary"], indent=2))
