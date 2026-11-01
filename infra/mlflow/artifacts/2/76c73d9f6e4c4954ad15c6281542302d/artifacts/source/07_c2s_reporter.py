"""
M7: Reporteador C2S — GEMAGENTICDI
GEN-MAMA-MX · Capa 3: Matriz de Agentes Clínicos

Genera fichas técnicas por combinación candidata Tier 1 y
reportes ejecutivos para oncólogos/investigadores usando Claude API.
"""

import json
import logging
import sys
import warnings
import os
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore")


ANTHROPIC_API_KEY = None  # Set via environment or config


def load_config(config_path: str) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def get_client():
    """Inicializa cliente Anthropic."""
    global ANTHROPIC_API_KEY

    if ANTHROPIC_API_KEY is None:
        ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

    if not ANTHROPIC_API_KEY:
        ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set — Claude API calls will be stubbed")
        return None

    try:
        from anthropic import Anthropic
        return Anthropic(api_key=ANTHROPIC_API_KEY)
    except ImportError:
        logger.warning("anthropic package not installed — Claude API calls will be stubbed")
        return None


SYSTEM_PROMPT = """Eres el reporteador clínico C2S de GEMAGENTICDI, un agente de descubrimiento de combinaciones farmacológicas para tumores fríos de mama.

Para cada combinación候选aria Tier 1, genera una ficha técnica completa con:
1. Resumen ejecutivo del mecanismo de acción propuesto
2. Estrategia de rescate inmune (cómo la combinación ataca al tumor frío)
3. Evidencia computacional (docking, scores C2S, sinergia)
4. Roadmap de validación experimental sugerido
5. Consideraciones de viabilidad clínica en México

Responde siempre en formato JSON estructurado según el schema de salida.
Sé conciso pero completo. Usa terminología oncológica precisa."""


USER_PROMPT_TEMPLATE = """Genera la ficha técnica para la siguiente combinación C2S-Scale:

**Combinación**: {drug_a} + {drug_b}
**Estrategia**: {target_strategy}
**Score C2S**: {c2s_score} (Tier {tier})
**Subtipo tumor frío**: {cold_subtype}

**Scores componentes**:
- C1 (Cobertura inmune): {c1}
- C2 (Sinergia): {c2}
- C3 (Seguridad ADMET): {c3}
- C4 (Novedad): {c4}
- C5 (Viabilidad MX): {c5}

**Resultados docking**:
{docking_results}

**Narrativa de novedad**: {novelty_statement}

Genera el reporte JSON con los siguientes campos:
{{
  "combination_id": "{combination_id}",
  "drug_a": "{drug_a}",
  "drug_b": "{drug_b}",
  "third_agent": {third_agent},
  "target_strategy": "{target_strategy}",
  "cold_tumor_subtype": "{cold_subtype}",
  "c2s_score": {c2s_score},
  "tier": {tier},
  "components": {{
    "C1_immune_coverage": {c1},
    "C2_synergy_score": {c2},
    "C3_safety_score": {c3},
    "C4_novelty_score": {c4},
    "C5_clinical_feasibility": {c5}
  }},
  "novelty_statement": "<narrativa de mecanismo propuesta>",
  "docking_results": <docking results dict>,
  "experimental_roadmap": ["paso1", "paso2", ...],
  "references_similar": [],
  "generated_by": "GEMAGENTICDI v1.0 — GEN-MAMA-MX C2S-Scale"
}}"""


def generate_candidate_report(
    candidate: dict,
    use_api: bool = True
) -> dict:
    """Genera reporte estructurado para una combinación candidate."""

    client = get_client()

    # Format docking results
    docking = candidate.get("docking_results", {})
    docking_str = json.dumps(docking, indent=2) if docking else "No docking validation available"

    # Format prompt
    components = candidate.get("components", {})
    c1 = components.get("C1_immune_coverage", 0)
    c2 = components.get("C2_synergy_score", 0)
    c3 = components.get("C3_safety_score", 0)
    c4 = components.get("C4_novelty_score", 0)
    c5 = components.get("C5_clinical_feasibility", 0)

    prompt = USER_PROMPT_TEMPLATE.format(
        combination_id=candidate.get("combination_id", "C2S-MX-0000"),
        drug_a=candidate.get("drug_a", ""),
        drug_b=candidate.get("drug_b", ""),
        third_agent=json.dumps(candidate.get("third_agent")),
        target_strategy=candidate.get("target_strategy", ""),
        cold_subtype=candidate.get("cold_tumor_subtype", ""),
        c2s_score=candidate.get("c2s_score", 0),
        tier=candidate.get("tier", 0),
        c1=round(c1, 3),
        c2=round(c2, 3),
        c3=round(c3, 3),
        c4=round(c4, 3),
        c5=round(c5, 3),
        docking_results=docking_str,
        novelty_statement=candidate.get("novelty_statement", "")
    )

    if client and use_api:
        try:
            response = client.messages.create(
                model="claude-opus-4-7",
                max_tokens=2048,
                temperature=0.3,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = response.content[0].text

            # Parse JSON from response
            try:
                # Try to extract JSON block
                if "```json" in response_text:
                    json_start = response_text.find("```json") + 7
                    json_end = response_text.find("```", json_start)
                    report = json.loads(response_text[json_start:json_end])
                else:
                    report = json.loads(response_text)

                # Merge with original candidate data
                for key in ["docking_results", "experimental_roadmap"]:
                    if key not in report and key in candidate:
                        report[key] = candidate[key]

                return report

            except json.JSONDecodeError:
                logger.warning(f"Failed to parse JSON from Claude response for {candidate.get('combination_id')}")
                return candidate

        except Exception as e:
            logger.warning(f"Claude API call failed: {e} — using candidate data directly")
            return candidate
    else:
        # Stub: return candidate data with enhanced novelty statement
        return generate_stub_report(candidate)


def generate_stub_report(candidate: dict) -> dict:
    """Genera reporte stub cuando Claude API no está disponible."""

    components = candidate.get("components", {})
    drug_a = candidate.get("drug_a", "")
    drug_b = candidate.get("drug_b", "")
    strategy = candidate.get("target_strategy", "")

    novelty = f"Combinación {drug_a} + {drug_b} ({strategy}) no reportada previamente en la literatura. Mecanismo propuesto:..."

    report = candidate.copy()
    report["novelty_statement"] = novelty
    report["_reporter_note"] = "Generated by GEMAGENTICDI M7 reporter (stub mode)"
    return report


def generate_executive_summary(tier1_candidates: list[dict]) -> dict:
    """Genera resumen ejecutivo de todas las combinaciones Tier 1."""

    summary = {
        "total_tier1": len(tier1_candidates),
        "date_generated": pd.Timestamp.now().isoformat(),
        "generated_by": "GEMAGENTICDI v1.0 — GEN-MAMA-MX C2S-Scale",
        "candidates": []
    }

    for candidate in tier1_candidates:
        components = candidate.get("components", {})
        summary["candidates"].append({
            "combination_id": candidate.get("combination_id"),
            "drugs": f"{candidate.get('drug_a')} + {candidate.get('drug_b')}",
            "strategy": candidate.get("target_strategy"),
            "c2s_score": candidate.get("c2s_score"),
            "C1": components.get("C1_immune_coverage"),
            "C2": components.get("C2_synergy_score"),
            "C3": components.get("C3_safety_score"),
            "C4": components.get("C4_novelty_score"),
            "C5": components.get("C5_clinical_feasibility"),
            "docking_available": bool(candidate.get("docking_results"))
        })

    # Sort by C2S score
    summary["candidates"].sort(key=lambda x: x["c2s_score"], reverse=True)

    return summary


def run_batch_reports(
    candidates: list[dict],
    output_dir: Path,
    use_api: bool = False
) -> dict:
    """Genera reportes para todas las combinaciones candidatas."""

    reports = []
    for candidate in candidates:
        combo_id = candidate.get("combination_id", "UNK")
        logger.info(f"Generating report for {combo_id}...")

        report = generate_candidate_report(candidate, use_api=use_api)
        reports.append(report)

        # Save individual report
        report_path = output_dir / f"{combo_id}_report.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

    return {"reports": reports}


def run_c2s_reporter(
    config_path: str = None,
    candidates_json: str = None,
    docking_results_json: str = None,
    novelty_reports_dir: str = None,
    output_dir: str = None,
    use_api: bool = False
):
    """Main entry point for M7."""

    base_dir = Path(__file__).parent.parent
    config_path = config_path or str(base_dir / "config.yaml")
    output_dir = output_dir or str(base_dir / "outputs" / "candidates")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== M7: C2S Reporter ===")

    # Load config
    config = load_config(config_path)

    # Load candidates (with docking results if available)
    if candidates_json and Path(candidates_json).exists():
        with open(candidates_json) as f:
            candidates = json.load(f)
    else:
        tier1_path = base_dir / "outputs" / "candidates" / "tier1_candidates.json"
        tier2_path = base_dir / "outputs" / "candidates" / "tier2_candidates.json"
        
        candidates = []
        logger.info(f"Checking for candidates in {tier1_path} and {tier2_path}")
        if tier1_path.exists():
            with open(tier1_path) as f:
                t1 = json.load(f)
                logger.info(f"Loaded {len(t1)} Tier 1 candidates")
                candidates.extend(t1)
        
        # If no Tier 1, include top Tier 2
        if not candidates and tier2_path.exists():
            with open(tier2_path) as f:
                tier2 = json.load(f)
                logger.info(f"Loaded {len(tier2)} Tier 2 candidates (Tier 1 was empty)")
                tier2.sort(key=lambda x: x.get("c2s_score", 0), reverse=True)
                candidates.extend(tier2[:20]) # Limit to top 20 for reporting
    
    logger.info(f"Total candidates for reporting: {len(candidates)}")
    if not candidates:
        logger.warning("No candidates found — skipping reporting")
        return {"reports": [], "executive_summary": {}}

    # Load docking results if available
    docking_path = base_dir / "outputs" / "docking_validation" / "vina_results.json"
    if docking_path.exists() and docking_results_json is None:
        with open(docking_path) as f:
            docking_results = json.load(f)

        # Merge docking results into candidates
        docking_map = {
            c.get("combination_id"): c.get("docking_results", {})
            for c in docking_results
        }
        for candidate in candidates:
            cid = candidate.get("combination_id")
            if cid in docking_map:
                candidate["docking_results"] = docking_map[cid]

    # Load novelty reports if available
    novelty_dir = Path(output_dir).parent / "novelty_reports"
    if novelty_dir.exists():
        novelty_map = {}
        for json_file in novelty_dir.glob("*_novelty.json"):
            with open(json_file) as f:
                novelty = json.load(f)
                key = f"{novelty.get('drug_a')}|{novelty.get('drug_b')}"
                novelty_map[key] = novelty

        for candidate in candidates:
            key = f"{candidate.get('drug_a')}|{candidate.get('drug_b')}"
            if key in novelty_map:
                candidate["novelty_report"] = novelty_map[key]
                # Update C4 novelty score if available
                novelty_score = novelty_map[key].get("novelty_score")
                if novelty_score is not None and "components" in candidate:
                    candidate["components"]["C4_novelty_score"] = novelty_score

    # Generate reports
    reports = run_batch_reports(candidates, output_dir, use_api=use_api)

    # Generate executive summary
    executive = generate_executive_summary(candidates)

    exec_path = output_dir / "executive_summary.json"
    with open(exec_path, "w") as f:
        json.dump(executive, f, indent=2)
    logger.info(f"Executive summary saved to {exec_path}")

    # Save combined output
    combined_path = output_dir / "all_candidates_with_reports.json"
    with open(combined_path, "w") as f:
        json.dump(candidates, f, indent=2)
    logger.info(f"Combined candidates with reports saved to {combined_path}")

    logger.info(f"=== M7 Complete: {len(candidates)} reportes generados ===")

    return {
        "reports": reports["reports"],
        "executive_summary": executive
    }


if __name__ == "__main__":
    result = run_c2s_reporter()
    print(f"Generated {len(result['reports'])} reports")
