"""
M8: Dashboard Generator — GEMAGENTICDI
GEN-MAMA-MX · Capa 3: Matriz de Agentes Clínicos

Genera un dashboard visual (Markdown/HTML) de los descubrimientos C2S-Scale.
"""

import json
import logging
import pandas as pd
from pathlib import Path
import yaml
from rich.console import Console
from rich.table import Table

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
console = Console()

def load_config(config_path: str) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def generate_markdown_dashboard(candidates: list[dict], output_path: Path):
    """Genera dashboard en formato Markdown."""
    
    md = "# 🔬 GEMAGENTICDI Discovery Dashboard\n"
    md += "## C2S-Scale: Combinaciones para Tumores Fríos\n\n"
    
    md += "| ID | Combinación | Estrategia | Score C2S | Tier |\n"
    md += "|:---|:---|:---|:---|:---|\n"
    
    for c in candidates:
        tier_label = f"⭐ Tier {c['tier']}" if c['tier'] <= 2 else f"Tier {c['tier']}"
        md += f"| {c['combination_id']} | **{c['drug_a']} + {c['drug_b']}** | {c['target_strategy']} | {c['c2s_score']} | {tier_label} |\n"
    
    md += "\n\n---\n"
    md += "### Top 3 Candidatos - Ficha Técnica Detallada\n\n"
    
    for c in candidates[:3]:
        md += f"#### {c['combination_id']}: {c['drug_a']} + {c['drug_b']}\n"
        md += f"- **Estrategia**: {c['target_strategy']}\n"
        md += f"- **Score Global**: {c['c2s_score']}\n"
        
        comp = c.get('components', {})
        md += f"- **Desglose C2S**:\n"
        md += f"  - Cobertura Inmune (C1): {comp.get('C1_immune_coverage', 0):.2f}\n"
        md += f"  - Sinergia (C2): {comp.get('C2_synergy_score', 0):.2f}\n"
        md += f"  - Seguridad (C3): {comp.get('C3_safety_score', 0):.2f}\n"
        md += f"  - Novedad (C4): {comp.get('C4_novelty_score', 0):.2f}\n"
        md += f"  - Viabilidad MX (C5): {comp.get('C5_clinical_feasibility', 0):.2f}\n"
        
        if c.get('novelty_statement'):
            md += f"- **Mecanismo Propuesto**: {c['novelty_statement']}\n"
        
        md += "\n"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md)
    
    logger.info(f"Markdown dashboard saved to {output_path}")

def print_rich_summary(candidates: list[dict]):
    """Imprime resumen visual en la terminal."""
    
    table = Table(title="GEMAGENTICDI — Top Discovery Candidates")
    
    table.add_column("ID", style="cyan")
    table.add_column("Combination", style="bold green")
    table.add_column("Strategy", style="magenta")
    table.add_column("C2S Score", justify="right", style="yellow")
    table.add_column("Tier", justify="center")
    
    for c in candidates[:15]:
        tier_color = "bold gold1" if c['tier'] == 1 else "bold silver" if c['tier'] == 2 else "white"
        table.add_row(
            c['combination_id'],
            f"{c['drug_a']} + {c['drug_b']}",
            c['target_strategy'][:40],
            str(c['c2s_score']),
            f"[{tier_color}]Tier {c['tier']}[/]"
        )
    
    console.print(table)

def run_dashboard_generator(
    config_path: str = None,
    candidates_json: str = None,
    output_dir: str = None
):
    """Main entry point for M8."""
    
    base_dir = Path(__file__).parent.parent
    config_path = config_path or str(base_dir / "config.yaml")
    output_dir = output_dir or str(base_dir / "outputs" / "dashboard")
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("=== M8: Dashboard Generator ===")
    
    # Load candidates
    if not candidates_json or not Path(candidates_json).exists():
        candidates_json = base_dir / "outputs" / "candidates" / "all_candidates_with_reports.json"
        if not Path(candidates_json).exists():
            # Fallback to synergy map if reports not ready
            candidates_json = base_dir / "outputs" / "synergy_maps" / "c2s_scores_full.json"

    if not Path(candidates_json).exists():
        logger.error(f"No candidates file found at {candidates_json}")
        return
    
    with open(candidates_json) as f:
        candidates = json.load(f)
    
    # Filter only Tiers 1-3
    top_candidates = [c for c in candidates if c.get('tier', 0) > 0]
    top_candidates.sort(key=lambda x: x['c2s_score'], reverse=True)
    
    # Generate Markdown
    md_path = output_dir / "discovery_report.md"
    generate_markdown_dashboard(top_candidates, md_path)
    
    # Print rich summary
    print_rich_summary(top_candidates)
    
    logger.info(f"=== M8 Complete: Dashboard generated for {len(top_candidates)} candidates ===")
    return {"dashboard_md": str(md_path)}

if __name__ == "__main__":
    run_dashboard_generator()
