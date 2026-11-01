"""
mlflow_tracker.py — Integración MLflow para GEMAGENTICDI
GEN-MAMA-MX · Capa 3: Matriz de Agentes Clínicos

Arquitectura de runs:
  Run padre  "di_M1-M8"        ← run del pipeline completo (rango real ejecutado)
    ├─ Run hijo  "M1_cold_tumor_classifier"
    ├─ Run hijo  "M2_target_mapper"
    ├─ Run hijo  "M3_combination_space"
    ├─ Run hijo  "M4_c2s_synergy"
    ├─ Run hijo  "M5_docking_validator"
    ├─ Run hijo  "M6_novelty_miner"
    ├─ Run hijo  "M7_c2s_reporter"
    └─ Run hijo  "M8_dashboard"

El nombre del run padre se genera dinámicamente en run_pipeline.py
como f"di_{actual_start}-{actual_end}" según los módulos realmente ejecutados.
Esto permite ver cada módulo como un paso individual en la UI de MLflow,
con sus propios parámetros, métricas y artefactos.
"""

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Nombres legibles por módulo
MODULE_NAMES = {
    "M1": "M1_cold_tumor_classifier",
    "M2": "M2_target_mapper",
    "M3": "M3_combination_space",
    "M4": "M4_c2s_synergy",
    "M5": "M5_docking_validator",
    "M6": "M6_novelty_miner",
    "M7": "M7_c2s_reporter",
    "M8": "M8_dashboard",
}

# Scripts fuente de cada módulo (relativos a src/)
MODULE_SCRIPTS = {
    "M1": "01_cold_tumor_classifier.py",
    "M2": "02_target_mapper.py",
    "M3": "03_combination_space_generator.py",
    "M4": "04_c2s_synergy_engine.py",
    "M5": "05_docking_validator.py",
    "M6": "06_novelty_miner.py",
    "M7": "07_c2s_reporter.py",
    "M8": "08_dashboard_generator.py",
}


class MLflowTracker:
    """Wrapper sobre mlflow con soporte de runs anidados para GEMAGENTICDI."""

    def __init__(self):
        self._mlflow = None
        self._parent_run = None
        self._child_run = None
        self._active = False
        self._experiment_id = None
        self._setup()

    def _setup(self):
        tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "")
        if not tracking_uri:
            logger.info("MLFLOW_TRACKING_URI no configurada — MLflow deshabilitado")
            return
        try:
            import mlflow
            self._mlflow = mlflow
            mlflow.set_tracking_uri(tracking_uri)

            experiment_name = os.environ.get("MLFLOW_EXPERIMENT", "GEMAMX-M1-M5")
            experiment = mlflow.get_experiment_by_name(experiment_name)
            if experiment is None:
                self._experiment_id = mlflow.create_experiment(experiment_name)
            else:
                self._experiment_id = experiment.experiment_id
            mlflow.set_experiment(experiment_name)

            logger.info(f"MLflow conectado: {tracking_uri} | experimento: {experiment_name}")
            self._active = True
        except Exception as e:
            logger.warning(f"MLflow no disponible: {e}")
            self._active = False

    @property
    def active(self) -> bool:
        return self._active

    # -------------------------------------------------------------------------
    # Gestión de runs
    # -------------------------------------------------------------------------

    def start_pipeline_run(self, run_name: str, tags: Optional[dict] = None):
        """Inicia el run padre del pipeline."""
        if not self._active:
            return
        default_tags = {
            "pipeline": "GEMAGENTICDI",
            "version": "1.0",
            "git_commit": os.environ.get("GEMAMX_GIT_COMMIT", "local"),
            "use_mock": os.environ.get("GEMAGENTICDI_USE_MOCK", "0"),
        }
        if tags:
            default_tags.update(tags)
        try:
            self._parent_run = self._mlflow.start_run(run_name=run_name, tags=default_tags)
            logger.info(f"MLflow run padre iniciado: {self._parent_run.info.run_id}")
        except Exception as e:
            logger.warning(f"Error iniciando run padre: {e}")
            self._active = False
        else:
            # Log run_pipeline.py como código fuente del pipeline padre
            self._log_source_file("run_pipeline.py")
            self._log_source_file("mlflow_tracker.py")

    def start_module_run(self, module: str):
        """Inicia un run hijo para un módulo. Requiere run padre activo."""
        if not self._active or self._parent_run is None:
            return
        run_name = MODULE_NAMES.get(module, module)
        try:
            self._child_run = self._mlflow.start_run(
                run_name=run_name,
                nested=True,
                tags={"module": module, "step": run_name},
            )
            # Log del código fuente del módulo — visible en MLflow UI > Artifacts > source/
            self._log_source_file(MODULE_SCRIPTS.get(module, ""))
        except Exception as e:
            logger.warning(f"Error iniciando run hijo {module}: {e}")
            self._child_run = None

    def end_module_run(self, status: str = "FINISHED"):
        """Cierra el run hijo activo."""
        if not self._active or self._child_run is None:
            return
        try:
            self._mlflow.end_run(status=status)
            self._child_run = None
        except Exception as e:
            logger.warning(f"Error cerrando run hijo: {e}")

    def end_pipeline_run(self, status: str = "FINISHED"):
        """Cierra el run padre."""
        if not self._active or self._parent_run is None:
            return
        try:
            # Asegurarse de que no haya child run abierto
            if self._child_run is not None:
                self._mlflow.end_run()
                self._child_run = None
            self._mlflow.end_run(status=status)
            logger.info("MLflow run pipeline finalizado")
        except Exception as e:
            logger.warning(f"Error cerrando run padre: {e}")

    # -------------------------------------------------------------------------
    # Log helpers
    # -------------------------------------------------------------------------

    def _log_params(self, params: dict):
        if not self._active:
            return
        try:
            items = list(params.items())
            for i in range(0, len(items), 100):
                self._mlflow.log_params(dict(items[i:i + 100]))
        except Exception as e:
            logger.warning(f"log_params error: {e}")

    def _log_metrics(self, metrics: dict, step: Optional[int] = None):
        if not self._active:
            return
        try:
            self._mlflow.log_metrics(metrics, step=step)
        except Exception as e:
            logger.warning(f"log_metrics error: {e}")

    def _log_artifact(self, local_path: str):
        if not self._active:
            return
        try:
            if Path(local_path).exists():
                self._mlflow.log_artifact(local_path)
        except Exception as e:
            logger.warning(f"log_artifact error ({local_path}): {e}")

    def _log_artifacts_dir(self, dir_path: str, artifact_path: Optional[str] = None):
        """Loguea todos los archivos de un directorio."""
        if not self._active:
            return
        try:
            p = Path(dir_path)
            if p.exists() and p.is_dir():
                self._mlflow.log_artifacts(str(p), artifact_path=artifact_path)
        except Exception as e:
            logger.warning(f"log_artifacts_dir error ({dir_path}): {e}")

    def _log_source_file(self, filename: str):
        """Sube el script .py fuente como artefacto bajo 'source/'.
        Visible en MLflow UI → run → pestaña Artifacts → source/<filename>.
        """
        if not self._active or not filename:
            return
        try:
            # El script está en el mismo directorio que mlflow_tracker.py (src/)
            src_dir = Path(__file__).parent
            script_path = src_dir / filename
            if script_path.exists():
                self._mlflow.log_artifact(str(script_path), artifact_path="source")
        except Exception as e:
            logger.warning(f"_log_source_file error ({filename}): {e}")

    # -------------------------------------------------------------------------
    # Pipeline-level params (en el run padre)
    # -------------------------------------------------------------------------

    def log_pipeline_params(self, modules_to_run: list, start_from: str, end_at: str):
        if not self._active:
            return
        self._log_params({
            "modules_run": ",".join(modules_to_run),
            "start_from": start_from or "M1",
            "end_at": end_at or "M8",
            "use_mock": os.environ.get("GEMAGENTICDI_USE_MOCK", "0"),
            "experiment": os.environ.get("MLFLOW_EXPERIMENT", "GEMAMX-M1-M5"),
        })

    def log_pipeline_summary(self, results: dict, modules_run: list):
        if not self._active:
            return
        n_success = sum(1 for r in results.values() if r.get("status") == "success")
        n_total = len(results)
        self._log_metrics({
            "pipeline_modules_success": n_success,
            "pipeline_modules_total": n_total,
            "pipeline_success_rate": round(n_success / n_total, 4) if n_total > 0 else 0,
        })

    # -------------------------------------------------------------------------
    # Módulos — cada uno abre/cierra su run hijo
    # -------------------------------------------------------------------------

    def log_m1(self, df_output, output_dir: str):
        """M1: Clasificador de tumor frío."""
        self.start_module_run("M1")
        if not self._active:
            return
        try:
            # df_output es un DataFrame con columnas classification, cold_subtype, cold_score
            import pandas as pd
            n_samples = len(df_output)
            clf_counts = df_output["classification"].value_counts().to_dict() if "classification" in df_output.columns else {}
            subtype_counts = df_output["cold_subtype"].value_counts().to_dict() if "cold_subtype" in df_output.columns else {}
            cold_scores = df_output["cold_score"].dropna() if "cold_score" in df_output.columns else pd.Series([])

            self._log_params({
                "m1.data_source":      "mock" if os.environ.get("GEMAGENTICDI_USE_MOCK", "0") == "1" else "loki",
                "m1.cold_threshold":   "0.65",
                "m1.cd8a_low_cutoff":  "1.5",
                "m1.tgfbeta_high_cutoff": "3.0",
            })
            self._log_metrics({
                "m1.n_samples":             n_samples,
                "m1.cold_count":            clf_counts.get("Cold", 0),
                "m1.warm_count":            clf_counts.get("Warm", 0),
                "m1.hot_count":             clf_counts.get("Hot", 0),
                "m1.cold_fraction":         round(clf_counts.get("Cold", 0) / n_samples, 4) if n_samples > 0 else 0,
                "m1.mean_cold_score":       round(float(cold_scores.mean()), 4) if len(cold_scores) > 0 else 0,
                "m1.max_cold_score":        round(float(cold_scores.max()), 4) if len(cold_scores) > 0 else 0,
                "m1.claudin_low_count":     subtype_counts.get("Claudin-low", 0),
                "m1.basal_count":           subtype_counts.get("Basal", 0),
                "m1.immune_excluded_count": subtype_counts.get("Immune-excluded", 0),
            })

            # Artefactos
            self._log_artifact(str(Path(output_dir) / "signature_scores.json"))
            csv_path = Path(output_dir).parent / "cold_tumor_classification.csv"
            self._log_artifact(str(csv_path))

            logger.info("MLflow M1 logueado")
        except Exception as e:
            logger.warning(f"Error logueando M1: {e}")
        finally:
            self.end_module_run()

    def log_m2(self, results: dict, output_dir: str):
        """M2: Target PPI Mapper."""
        self.start_module_run("M2")
        if not self._active:
            return
        try:
            hub_targets     = results.get("hub_targets", [])
            druggable       = results.get("druggable_targets", [])
            target_coverage = results.get("target_coverage", {})

            covered = sum(1 for v in target_coverage.values() if v.get("covered"))
            total_targets = len(target_coverage)

            # Estrategias únicas en los hubs
            strategies = set(h.get("strategy", "unknown") for h in hub_targets)

            # Top hub por hub_score
            top_hub = max(hub_targets, key=lambda h: h.get("hub_score", 0), default={})

            self._log_params({
                "m2.ppi_source":         "stub_curated",
                "m2.n_strategies":       len(strategies),
                "m2.strategies":         ",".join(sorted(strategies)),
                "m2.top_hub_gene":       top_hub.get("gene", "none"),
                "m2.top_hub_strategy":   top_hub.get("strategy", "none"),
            })
            self._log_metrics({
                "m2.n_hub_targets":        len(hub_targets),
                "m2.n_druggable_targets":  len(druggable),
                "m2.n_targets_covered":    covered,
                "m2.n_targets_total":      total_targets,
                "m2.coverage_fraction":    round(covered / total_targets, 4) if total_targets > 0 else 0,
                "m2.top_hub_score":        round(top_hub.get("hub_score", 0), 4),
                "m2.druggable_fraction":   round(len(druggable) / len(hub_targets), 4) if hub_targets else 0,
            })

            for fname in ["hub_targets.json", "druggable_targets.json",
                          "target_coverage.json", "ppi_network.json"]:
                self._log_artifact(str(Path(output_dir) / fname))

            logger.info("MLflow M2 logueado")
        except Exception as e:
            logger.warning(f"Error logueando M2: {e}")
        finally:
            self.end_module_run()

    def log_m3(self, matrix_meta: dict, admet_df, output_dir: str):
        """M3: Espacio combinatorio y ADMET."""
        self.start_module_run("M3")
        if not self._active:
            return
        try:
            n_drugs = len(matrix_meta.get("drugs", []))
            n_targets = len(matrix_meta.get("targets", []))

            valid_col = "_valid_smiles" if "_valid_smiles" in admet_df.columns else None
            valid_smiles = int(admet_df[valid_col].sum()) if valid_col else 0

            admet_col = admet_df["admet_score"].dropna() if "admet_score" in admet_df.columns else []
            mean_admet = float(admet_col.mean()) if len(admet_col) > 0 else 0.0
            min_admet  = float(admet_col.min())  if len(admet_col) > 0 else 0.0
            max_admet  = float(admet_col.max())  if len(admet_col) > 0 else 0.0

            pains_col = "pains_flag"
            n_pains = int((admet_df[pains_col] == True).sum()) if pains_col in admet_df.columns else 0

            self._log_params({
                "m3.n_drugs": n_drugs,
                "m3.n_targets": n_targets,
                "m3.n_combinations": n_drugs * n_targets,
                "m3.admet_max_mw": "900",
                "m3.admet_max_logp": "6.0",
            })
            self._log_metrics({
                "m3.valid_smiles": valid_smiles,
                "m3.invalid_smiles": n_drugs - valid_smiles,
                "m3.mean_admet_score": round(mean_admet, 4),
                "m3.min_admet_score": round(min_admet, 4),
                "m3.max_admet_score": round(max_admet, 4),
                "m3.pains_flagged": n_pains,
                "m3.admet_valid_fraction": round(valid_smiles / n_drugs, 4) if n_drugs > 0 else 0,
            })

            for fname in ["admet_scores.csv", "combination_matrix.json", "compound_clusters.json"]:
                self._log_artifact(str(Path(output_dir) / fname))

            logger.info("MLflow M3 logueado")
        except Exception as e:
            logger.warning(f"Error logueando M3: {e}")
        finally:
            self.end_module_run()

    def log_m4(self, results: dict, output_dir: str):
        """M4: Motor de sinergias C2S-Scale."""
        self.start_module_run("M4")
        if not self._active:
            return
        try:
            tier1 = results.get("tier1", [])
            tier2 = results.get("tier2", [])
            tier3 = results.get("tier3", [])
            full  = results.get("full_results", [])

            scores = [r["c2s_score"] for r in full if "c2s_score" in r]
            top_score  = max(scores) if scores else 0.0
            mean_score = sum(scores) / len(scores) if scores else 0.0
            min_score  = min(scores) if scores else 0.0

            top = tier1[0] if tier1 else (tier2[0] if tier2 else None)

            self._log_params({
                "m4.top_candidate_id":    top["combination_id"] if top else "none",
                "m4.top_candidate_drugs": f"{top['drug_a']} + {top['drug_b']}" if top else "none",
                "m4.top_strategy":        top.get("target_strategy", "none")[:200] if top else "none",
                "m4.tier1_threshold":     "65",
                "m4.tier2_threshold":     "45",
            })
            self._log_metrics({
                "m4.total_combinations": len(full),
                "m4.tier1_count":        len(tier1),
                "m4.tier2_count":        len(tier2),
                "m4.tier3_count":        len(tier3),
                "m4.discarded_count":    len(full) - len(tier1) - len(tier2) - len(tier3),
                "m4.top_c2s_score":      round(top_score, 2),
                "m4.mean_c2s_score":     round(mean_score, 2),
                "m4.min_c2s_score":      round(min_score, 2),
            })

            # Componentes promedio del top 20
            top20 = sorted(full, key=lambda x: x.get("c2s_score", 0), reverse=True)[:20]
            comp_metrics = {}
            for ck in ["C1_immune_coverage", "C2_synergy_score", "C3_safety_score",
                       "C4_novelty_score", "C5_clinical_feasibility"]:
                vals = [r["components"][ck] for r in top20
                        if "components" in r and ck in r["components"]]
                if vals:
                    comp_metrics[f"m4.top20_mean_{ck.lower()}"] = round(sum(vals) / len(vals), 4)
            if comp_metrics:
                self._log_metrics(comp_metrics)

            # Distribución de estrategias en top20
            strat_counts: dict = {}
            for r in top20:
                strat = r.get("target_strategy", "unknown")
                strat_counts[strat] = strat_counts.get(strat, 0) + 1
            self._log_params({
                f"m4.top20_strategy_{i}": f"{s} ({c})"
                for i, (s, c) in enumerate(sorted(strat_counts.items(), key=lambda x: -x[1])[:5])
            })

            # Artefactos
            synergy_dir = Path(output_dir) / "synergy_maps"
            self._log_artifact(str(synergy_dir / "c2s_scores_full.json"))
            candidates_dir = Path(output_dir) / "candidates"
            for fname in ["tier1_candidates.json", "tier2_candidates.json"]:
                self._log_artifact(str(candidates_dir / fname))

            logger.info("MLflow M4 logueado")
        except Exception as e:
            logger.warning(f"Error logueando M4: {e}")
        finally:
            self.end_module_run()

    def log_m5(self, results: dict, output_dir: str):
        """M5: Docking molecular."""
        self.start_module_run("M5")
        if not self._active:
            return
        try:
            validated = results.get("validated", [])
            n_docked = sum(1 for c in validated if c.get("docking_results"))
            all_affinities = []
            for c in validated:
                for dv in c.get("docking_results", {}).values():
                    aff = dv.get("affinity_kcal_mol")
                    if aff is not None:
                        all_affinities.append(aff)

            vina_available = "vina" in str(results).lower() and results.get("note") != "No candidates"
            self._log_params({
                "m5.vina_available": str(vina_available),
                "m5.skip_reason":    results.get("note", "ok"),
            })
            self._log_metrics({
                "m5.validated_combinations":  n_docked,
                "m5.total_docking_poses":     len(all_affinities),
                "m5.best_affinity_kcal_mol":  round(min(all_affinities), 3) if all_affinities else 0.0,
                "m5.mean_affinity_kcal_mol":  round(sum(all_affinities) / len(all_affinities), 3) if all_affinities else 0.0,
            })

            self._log_artifact(str(Path(output_dir) / "vina_results.json"))
            logger.info("MLflow M5 logueado")
        except Exception as e:
            logger.warning(f"Error logueando M5: {e}")
        finally:
            self.end_module_run()

    def log_m6(self, results: dict, output_dir: str):
        """M6: Novedad científica."""
        self.start_module_run("M6")
        if not self._active:
            return
        try:
            summary = results.get("summary", {})
            total = summary.get("total", 0)

            self._log_metrics({
                "m6.total_mined":          total,
                "m6.novel_count":          summary.get("novel", 0),
                "m6.sparsely_reported":    summary.get("sparsely_reported", 0),
                "m6.moderately_reported":  summary.get("moderately_reported", 0),
                "m6.well_reported":        summary.get("well_reported", 0),
                "m6.novel_fraction":       round(summary.get("novel", 0) / total, 4) if total > 0 else 0,
            })

            self._log_artifact(str(Path(output_dir) / "novelty_summary.json"))
            logger.info("MLflow M6 logueado")
        except Exception as e:
            logger.warning(f"Error logueando M6: {e}")
        finally:
            self.end_module_run()

    def log_m7(self, results: dict, output_dir: str):
        """M7: Reporteador C2S."""
        self.start_module_run("M7")
        if not self._active:
            return
        try:
            reports = results.get("reports", [])
            self._log_params({
                "m7.claude_api_used": str(bool(os.environ.get("ANTHROPIC_API_KEY"))),
                "m7.report_mode":     "api" if os.environ.get("ANTHROPIC_API_KEY") else "stub",
            })
            self._log_metrics({
                "m7.reports_generated": len(reports),
            })

            for fname in ["executive_summary.json", "all_candidates_with_reports.json"]:
                self._log_artifact(str(Path(output_dir) / fname))

            logger.info("MLflow M7 logueado")
        except Exception as e:
            logger.warning(f"Error logueando M7: {e}")
        finally:
            self.end_module_run()

    def log_m8(self, results: dict, output_dir: str):
        """M8: Dashboard generator."""
        self.start_module_run("M8")
        if not self._active:
            return
        try:
            md_path = results.get("dashboard_md", "")
            if md_path:
                self._log_artifact(md_path)
            logger.info("MLflow M8 logueado")
        except Exception as e:
            logger.warning(f"Error logueando M8: {e}")
        finally:
            self.end_module_run()
