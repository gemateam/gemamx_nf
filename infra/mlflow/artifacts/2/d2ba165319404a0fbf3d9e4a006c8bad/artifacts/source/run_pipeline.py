"""
run_pipeline.py — GEMAGENTICDI Pipeline Orchestrator
GEN-MAMA-MX · Capa 3: Matriz de Agentes Clínicos

Orquestador CLI que ejecuta los 7 módulos en orden de dependencia.
Permite ejecución parcial via --start_from / --end_at.

Uso:
    python run_pipeline.py                    # Ejecuta pipeline completo
    python run_pipeline.py --start_from M3   # Desde M3 en adelante
    python run_pipeline.py --end_at M4       # Hasta M4
    python run_pipeline.py --start_from M1 --end_at M5  # Rango M1-M5
"""

import argparse
import json
import logging
import os
import sys
import warnings
from pathlib import Path

# MLflow tracker (no falla si mlflow no está instalado)
try:
    from mlflow_tracker import MLflowTracker
except ImportError:
    MLflowTracker = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore")


MODULE_ORDER = ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8"]

MODULE_DEPS = {
    "M1": [],                    # Cold tumor classifier — independiente
    "M2": [],                    # Target mapper — puede usar stubs
    "M3": [],                    # Combination space — independiente
    "M4": ["M1", "M2", "M3"],   # Synergy engine — requiere M1+M2+M3
    "M5": ["M3", "M4"],         # Docking — requiere M3+M4
    "M6": ["M4"],                # Novelty miner — requiere M4
    "M7": ["M4", "M5", "M6"],   # Reporter — requiere M4+M5+M6
    "M8": ["M7"],                # Dashboard — requiere M7
}


def get_module_script(module: str, src_dir: Path) -> Path:
    """Retorna la ruta del script para un módulo dado."""
    module_scripts = {
        "M1": "01_cold_tumor_classifier.py",
        "M2": "02_target_mapper.py",
        "M3": "03_combination_space_generator.py",
        "M4": "04_c2s_synergy_engine.py",
        "M5": "05_docking_validator.py",
        "M6": "06_novelty_miner.py",
        "M7": "07_c2s_reporter.py",
        "M8": "08_dashboard_generator.py",
    }
    return src_dir / module_scripts[module]


def resolve_modules(start_from: str, end_at: str) -> list[str]:
    """Resuelve qué módulos ejecutar dado el rango."""

    if start_from and start_from not in MODULE_ORDER:
        raise ValueError(f"Módulo inválido: {start_from}. Opciones: {MODULE_ORDER}")
    if end_at and end_at not in MODULE_ORDER:
        raise ValueError(f"Módulo inválido: {end_at}. Opciones: {MODULE_ORDER}")

    start_idx = MODULE_ORDER.index(start_from) if start_from else 0
    end_idx = MODULE_ORDER.index(end_at) if end_at else len(MODULE_ORDER) - 1

    if start_idx > end_idx:
        raise ValueError(f"--start_from '{start_from}' comes after --end_at '{end_at}'")

    return MODULE_ORDER[start_idx:end_idx + 1]


def run_module(module: str, src_dir: Path, base_dir: Path, gemamx_root: str, extra_args: dict = None) -> dict:
    """Ejecuta un módulo individual y retorna el resultado."""

    logger.info(f"\n{'='*60}")
    logger.info(f"Ejecutando {module}")
    logger.info(f"{'='*60}")

    script = get_module_script(module, src_dir)
    if not script.exists():
        logger.error(f"Script no encontrado: {script}")
        return {"status": "error", "message": f"Script not found: {script}"}

    # Import and run the module
    import importlib.util

    spec = importlib.util.spec_from_file_location(module, script)
    module_lib = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module_lib)

    # Determine the run function name
    run_functions = {
        "M1": "run_cold_tumor_classifier",
        "M2": "run_target_mapper",
        "M3": "run_combination_space_generator",
        "M4": "run_c2s_synergy_engine",
        "M5": "run_docking_validator",
        "M6": "run_novelty_miner",
        "M7": "run_c2s_reporter",
        "M8": "run_dashboard_generator",
    }

    run_fn_name = run_functions[module]
    if not hasattr(module_lib, run_fn_name):
        logger.error(f"Módulo {module} no tiene función {run_fn_name}")
        return {"status": "error", "message": f"Function {run_fn_name} not found"}

    run_fn = getattr(module_lib, run_fn_name)

    # Build kwargs based on module
    kwargs = {"config_path": str(base_dir / "config.yaml")}

    if module == "M1":
        # Orden de prioridad para datos de expresión:
        # 1) env var GEO_EXPRESSION_TSV / GEMAGENTICDI_GEO_TSV  (datos reales GEO)
        # 2) tools/loki/outputs/predex/predex_slide_expression.tsv  (Loki real)
        # 3) mock si GEMAGENTICDI_USE_MOCK=1  (desarrollo sin datos)
        geo_tsv = (
            os.environ.get("GEMAGENTICDI_GEO_TSV")
            or os.environ.get("GEO_EXPRESSION_TSV")
        )
        if geo_tsv and Path(geo_tsv).exists():
            kwargs["expression_input"] = geo_tsv
            kwargs["use_mock"] = os.environ.get("GEMAGENTICDI_USE_MOCK", "0") == "1"
        else:
            use_mock_env = os.environ.get("GEMAGENTICDI_USE_MOCK", "0") == "1"
            kwargs["use_mock"] = use_mock_env
        kwargs["gemamx_root"] = gemamx_root

    elif module == "M3":
        kwargs["compound_csv"] = str(base_dir / "data" / "compound_libraries" / "compound_library.csv")
        kwargs["output_dir"] = str(base_dir / "data" / "combination_space")

    elif module == "M2":
        kwargs["combination_matrix_json"] = str(base_dir / "data" / "combination_space" / "combination_matrix.json")
        kwargs["output_dir"] = str(base_dir / "data" / "target_mapping")

    elif module == "M4":
        kwargs["compound_csv"] = str(base_dir / "data" / "compound_libraries" / "compound_library.csv")
        kwargs["combination_matrix_json"] = str(base_dir / "data" / "combination_space" / "combination_matrix.json")
        kwargs["admet_csv"] = str(base_dir / "data" / "combination_space" / "admet_scores.csv")
        kwargs["ppi_network_json"] = str(base_dir / "data" / "target_mapping" / "ppi_network.json")
        mx_local = base_dir / "data" / "mx_access_registry.json"
        if mx_local.exists():
            kwargs["mx_registry_json"] = str(mx_local)
        elif gemamx_root:
            kwargs["mx_registry_json"] = str(Path(gemamx_root) / "mx_access_registry.json")
        kwargs["output_dir"] = str(base_dir / "outputs")

    elif module == "M5":
        kwargs["compound_csv"] = str(base_dir / "data" / "compound_libraries" / "compound_library.csv")
        kwargs["candidates_json"] = str(base_dir / "outputs" / "candidates" / "tier1_candidates.json")
        kwargs["gemamx_root"] = gemamx_root
        kwargs["output_dir"] = str(base_dir / "outputs" / "docking_validation")

    elif module == "M6":
        kwargs["candidates_json"] = str(base_dir / "outputs" / "candidates" / "tier1_candidates.json")
        kwargs["output_dir"] = str(base_dir / "outputs" / "novelty_reports")

    elif module == "M7":
        kwargs["output_dir"] = str(base_dir / "outputs" / "candidates")

    elif module == "M8":
        kwargs["output_dir"] = str(base_dir / "outputs" / "dashboard")

    # Merge extra args
    if extra_args:
        kwargs.update(extra_args)

    try:
        result = run_fn(**kwargs)
        logger.info(f"{module} completado exitosamente")
        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"Error ejecutando {module}: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


def run_pipeline(
    start_from: str = None,
    end_at: str = None,
    gemamx_root: str = None,
    extra_args: dict = None
):
    """Ejecuta el pipeline completo o parcial."""

    # base_dir must be the project root (parent of src)
    src_script = Path(__file__)
    base_dir = src_script.parent.parent  # src/run_pipeline.py → src/ → project root
    src_dir = base_dir / "src"
    gemamx_root = gemamx_root or os.environ.get("GEMAMX_ROOT", "")

    logger.info(f"GEMAGENTICDI Pipeline")
    logger.info(f"Base directory: {base_dir}")
    logger.info(f"GEMAMX root: {gemamx_root}")

    # Resolve modules to run
    modules_to_run = resolve_modules(start_from, end_at)
    logger.info(f"Módulos a ejecutar: {modules_to_run}")

    # Check dependencies
    for module in modules_to_run:
        deps = MODULE_DEPS.get(module, [])
        missing_deps = [d for d in deps if d not in MODULE_ORDER[:MODULE_ORDER.index(module) + 1]]
        if missing_deps:
            logger.warning(f"{module} tiene dependencias faltantes: {missing_deps}")

    # --- MLflow setup ---
    tracker = MLflowTracker() if MLflowTracker else None
    # El nombre refleja el rango REAL ejecutado (no los defaults)
    actual_start = modules_to_run[0] if modules_to_run else (start_from or "M1")
    actual_end   = modules_to_run[-1] if modules_to_run else (end_at   or "M8")
    run_label = f"di_{actual_start}-{actual_end}"
    if tracker and tracker.active:
        tracker.start_pipeline_run(run_label)
        tracker.log_pipeline_params(modules_to_run, actual_start, actual_end)

    results = {}
    pipeline_status = "FINISHED"

    for module in modules_to_run:
        result = run_module(module, src_dir, base_dir, gemamx_root, extra_args)
        results[module] = result

        # --- Log per-module metrics to MLflow ---
        if tracker and tracker.active and result.get("status") == "success":
            # IMPORTANTE: res_data puede ser DataFrame (M1) o dict (M2-M8).
            # NO usar `or {}` porque un DataFrame no tiene valor booleano definido.
            res_data = result.get("result")
            outputs_dir = str(base_dir / "outputs")
            data_dir = str(base_dir / "data" / "combination_space")

            if module == "M1" and res_data is not None:
                tracker.log_m1(res_data, str(base_dir / "outputs" / "cold_tumor_signatures"))

            elif module == "M2" and res_data is not None:
                tracker.log_m2(res_data, str(base_dir / "data" / "target_mapping"))

            elif module == "M3" and res_data is not None:
                import pandas as pd
                admet_path = base_dir / "data" / "combination_space" / "admet_scores.csv"
                try:
                    admet_df = pd.read_csv(admet_path)
                except Exception:
                    admet_df = pd.DataFrame()
                tracker.log_m3(res_data, admet_df, data_dir)

            elif module == "M4" and res_data is not None:
                tracker.log_m4(res_data, outputs_dir)

            elif module == "M5" and res_data is not None:
                tracker.log_m5(res_data, str(base_dir / "outputs" / "docking_validation"))

            elif module == "M6" and res_data is not None:
                tracker.log_m6(res_data, str(base_dir / "outputs" / "novelty_reports"))

            elif module == "M7" and res_data is not None:
                tracker.log_m7(res_data, str(base_dir / "outputs" / "candidates"))

            elif module == "M8" and res_data is not None:
                tracker.log_m8(res_data, str(base_dir / "outputs" / "dashboard"))

        if result["status"] == "error":
            logger.error(f"Pipeline detenido en {module}")
            pipeline_status = "FAILED"
            break

    # Final summary
    logger.info(f"\n{'='*60}")
    logger.info("RESUMEN DEL PIPELINE")
    logger.info(f"{'='*60}")

    for module, result in results.items():
        status = result["status"]
        symbol = "[OK]" if status == "success" else "[FAIL]"
        logger.info(f"  {symbol} {module}: {status}")

    n_success = sum(1 for r in results.values() if r["status"] == "success")
    n_total = len(results)
    logger.info(f"\nTotal: {n_success}/{n_total} módulos completados")

    # --- Cerrar MLflow run ---
    if tracker and tracker.active:
        tracker.log_pipeline_summary(results, modules_to_run)
        tracker.end_pipeline_run(status=pipeline_status)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="GEMAGENTICDI Pipeline Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
    python run_pipeline.py                    # Pipeline completo
    python run_pipeline.py --start_from M3   # Solo M3-M7
    python run_pipeline.py --end_at M4        # M1-M4
    python run_pipeline.py --start_from M1 --end_at M5  # M1-M5
        """
    )

    parser.add_argument(
        "--start_from",
        choices=MODULE_ORDER,
        help="Comenzar desde este módulo (inclusive)"
    )
    parser.add_argument(
        "--end_at",
        choices=MODULE_ORDER,
        help="Terminar en este módulo (inclusive)"
    )
    parser.add_argument(
        "--gemamx_root",
        default=os.environ.get("GEMAMX_ROOT", ""),
        help="Ruta raíz del proyecto GEMAMX padre"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Modo verboso"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    results = run_pipeline(
        start_from=args.start_from,
        end_at=args.end_at,
        gemamx_root=args.gemamx_root
    )

    # Exit code based on results
    all_success = all(r["status"] == "success" for r in results.values())
    sys.exit(0 if all_success else 1)


if __name__ == "__main__":
    main()
