#!/usr/bin/env python3
"""LOG_MLFLOW — registra una corrida publicada en MLflow (sin bloquear resultados).

Estructura en el servidor:

  experimento GEMAMX-V1-NF
  └── run padre  = workflow.runName          (tags gemamx.run_name / git_commit)
      ├── hija ingest
      ├── hija fasta
      ├── hija structures
      ├── hija docking
      ├── hija metrics
      └── hija publish

Idempotencia: si ya existe un run con el mismo `gemamx.run_name`, se reutiliza;
las hijas se localizan por `gemamx.stage` y no se duplican. Reintentar el
proceso no crea runs nuevos.

Este proceso corre **después** de PUBLISH: si MLflow no responde, el proceso
falla con un mensaje claro pero el contrato `data/` ya está publicado y los
resultados no se invalidan.

No usa credenciales ni variables de entorno: la URI se pasa explícitamente.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import die, read_json, write_json  # noqa: E402

PARAM_KEY_RE = re.compile(r"[^A-Za-z0-9_.\-/ ]+")
PARAM_MAX_LEN = 500
STAGES = ("ingest", "fasta", "structures", "docking", "metrics", "publish")


def sanitize_key(key: str) -> str:
    return PARAM_KEY_RE.sub("_", key)[:250]


def flatten_params(data: object, prefix: str = "") -> dict[str, str]:
    """Aplana un JSON a pares clave/valor válidos para MLflow."""
    flat: dict[str, str] = {}

    def walk(value: object, path: str) -> None:
        if isinstance(value, dict):
            if not value:
                flat[sanitize_key(path)] = "{}"
            for key, child in value.items():
                walk(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, (list, tuple)):
            flat[sanitize_key(path)] = ",".join(str(v) for v in value)[:PARAM_MAX_LEN]
        elif value is None:
            flat[sanitize_key(path)] = "null"
        elif isinstance(value, bool):
            flat[sanitize_key(path)] = "true" if value else "false"
        else:
            flat[sanitize_key(path)] = str(value)[:PARAM_MAX_LEN]

    walk(data, prefix)
    return {k: v for k, v in flat.items() if k}


def metric_name(*parts: str) -> str:
    return sanitize_key(".".join(part for part in parts if part))


def load_optional(path: str | None) -> object:
    if not path:
        return {}
    return read_json(path)


def find_run(client, experiment_id: str, run_name: str, stage: str | None):
    filters = [f"tags.\"gemamx.run_name\" = '{run_name}'"]
    if stage:
        filters.append(f"tags.\"gemamx.stage\" = '{stage}'")
    found = client.search_runs(
        experiment_ids=[experiment_id],
        filter_string=" and ".join(filters),
        max_results=100,
        order_by=["attributes.start_time DESC"],
    )
    if stage:
        return found[0] if found else None
    return next((run for run in found if not run.data.tags.get("gemamx.stage")), None)


def ensure_experiment(client, name: str) -> str:
    experiment = client.get_experiment_by_name(name)
    if experiment is not None:
        return experiment.experiment_id
    # Mismo almacenamiento que el resto de experimentos de la plataforma.
    return client.create_experiment(name, artifact_location="mlflow-artifacts:/")


LEGACY_SOURCE_TAGS = ("gemamx.source_code", "mlflow.source.name")


def clear_legacy_source_tags(client, run_id: str) -> None:
    for key in LEGACY_SOURCE_TAGS:
        try:
            client.delete_tag(run_id, key)
        except Exception:
            pass


def stage_source_dir(source_code_dir: Path, stage: str) -> Path:
    path = source_code_dir / stage
    manifest = path / "source_manifest.json"
    if not path.is_dir() or not manifest.is_file():
        die(f"falta el snapshot de código para la etapa {stage}: {path}")
    files = [item for item in path.rglob("*") if item.is_file() and item.name != "source_manifest.json"]
    if not files:
        die(f"el snapshot de código está vacío para la etapa {stage}: {path}")
    return path

def log_stage(mlflow, client, experiment_id: str, run_name: str,
              stage: str, params: dict[str, str], metrics: dict[str, float],
              artifacts: list[str], tags: dict[str, str],
              source_code_dir: Path, dataset=None) -> tuple[str, bool]:
    source_dir = stage_source_dir(source_code_dir, stage)
    source_artifact = "source_code"
    source_file_count = sum(1 for path in source_dir.rglob("*") if path.is_file())
    stage_tags = {
        **tags,
        "gemamx.stage": stage,
        "gemamx.pipeline": "gemamx_nf",
        "gemamx.contract": "v1",
        "gemamx.source_code_artifact": source_artifact,
        "gemamx.source_code_files": str(source_file_count),
    }
    existing = find_run(client, experiment_id, run_name, stage)
    if existing is not None:
        clear_legacy_source_tags(client, existing.info.run_id)
        for key, value in stage_tags.items():
            client.set_tag(existing.info.run_id, key, value)
        client.log_artifacts(existing.info.run_id, str(source_dir), artifact_path=source_artifact)
        return existing.info.run_id, False

    with mlflow.start_run(run_name=f"{run_name}-{stage}", experiment_id=experiment_id,
                          nested=True, tags=stage_tags) as child:
        if params:
            mlflow.log_params(params)
        if metrics:
            mlflow.log_metrics(metrics)
        if dataset is not None:
            try:
                mlflow.log_input(dataset, context=stage)
            except Exception:
                pass
        for artifact in artifacts:
            path = Path(artifact)
            if path.is_file():
                mlflow.log_artifact(str(path))
            elif path.is_dir():
                mlflow.log_artifacts(str(path), artifact_path=path.name)
        mlflow.log_artifacts(str(source_dir), artifact_path=source_artifact)
        child_id = child.info.run_id
    return child_id, True


def main() -> int:
    parser = argparse.ArgumentParser(description="Registra la corrida en MLflow")
    parser.add_argument("--tracking-uri", required=True,
                        help="p. ej. http://host.docker.internal:5000")
    parser.add_argument("--experiment", default="GEMAMX-V1-NF")
    parser.add_argument("--run-name", required=True,
                        help="workflow.runName; identifica la corrida")
    parser.add_argument("--params", help="params.json de la corrida")
    parser.add_argument("--images", help="images.json (imágenes usadas)")
    parser.add_argument("--run-manifest", help="run_manifest.json de PUBLISH")
    parser.add_argument("--data-dir", help="directorio raíz data/ con todos los contratos")
    parser.add_argument("--source-code-dir", required=True,
                        help="snapshot de código por etapa generado por snapshot_mlflow_sources.py")
    parser.add_argument("--structural-metrics", help="structural_metrics.json")
    parser.add_argument("--vina-affinities", help="docking/vina_affinities.json")
    parser.add_argument("--artifact", action="append", default=[],
                        help="artefacto adicional (repetible)")
    parser.add_argument("--git-commit", default="")
    parser.add_argument("--out", help="JSON con los IDs registrados")
    args = parser.parse_args()

    run_name = args.run_name.strip()
    if not run_name:
        die("--run-name vacío")
    if not re.fullmatch(r"[A-Za-z0-9._\-]+", run_name):
        die(f"--run-name contiene caracteres no admitidos: {run_name!r}")

    try:
        import mlflow
        from mlflow import MlflowClient
    except ImportError:
        die("MLflow no está instalado en la imagen (se esperaba mlflow 2.x)")

    mlflow.set_tracking_uri(args.tracking_uri)
    client = MlflowClient(tracking_uri=args.tracking_uri)

    params_data = load_optional(args.params)
    images_data = load_optional(args.images)
    manifest_data = load_optional(args.run_manifest)
    structural = load_optional(args.structural_metrics)
    vina = load_optional(args.vina_affinities)

    if "v2_1" in args.experiment.lower():
        workflow_file = "main_v2_1.nf"
    elif "romero" in run_name.lower() or "v2" in args.experiment.lower():
        workflow_file = "main_v2.nf"
    elif "v3" in args.experiment.lower() or "tcga" in run_name.lower():
        workflow_file = "main_v3.nf"
    else:
        workflow_file = "main.nf"

    # Procedencia del contrato V3, si INGEST la publicó en data/.
    contract = None
    if args.data_dir:
        contract_path = Path(args.data_dir) / "contract_provenance.json"
        if contract_path.is_file():
            contract = read_json(contract_path)

    base_tags = {
        "gemamx.pipeline": "gemamx_nf",
        "gemamx.contract": "v1",
        "gemamx.run_name": run_name,
        "gemamx.git_commit": args.git_commit or "unknown",
        "gemamx.tracking_uri": args.tracking_uri,
        "gemamx.workflow_file": workflow_file,
    }
    if isinstance(contract, dict):
        version = str(contract.get("contract_version") or "")
        if version:
            base_tags["gemamx.contract"] = f"v{version.split('.')[0]}"
            base_tags["gemamx.contract_version"] = version
        for tag, key in (
            ("gemamx.bundle_id", "bundle_id"),
            ("gemamx.gdc_data_release", "gdc_data_release"),
            ("gemamx.mutation_scope", "mutation_scope"),
            ("gemamx.data_origin", "data_origin"),
            ("gemamx.curated", "curated"),
        ):
            if contract.get(key) is not None:
                base_tags[tag] = str(contract[key])

    try:
        experiment_id = ensure_experiment(client, args.experiment)
        parent = find_run(client, experiment_id, run_name, None)

        created_parent = parent is None
        if created_parent:
            with mlflow.start_run(run_name=run_name, experiment_id=experiment_id,
                                  tags=base_tags) as run:
                parent_id = run.info.run_id
                flat = flatten_params(params_data)
                if images_data:
                    for key, value in flatten_params(images_data, "images").items():
                        flat[key] = value
                if flat:
                    mlflow.log_params(flat)
        else:
            parent_id = parent.info.run_id

        clear_legacy_source_tags(client, parent_id)
        client.set_tag(parent_id, "gemamx.workflow_file", workflow_file)

        # Métricas resumen en el padre (no dependen del detalle por etapa).
        summary: dict[str, float] = {}
        if isinstance(structural, dict):
            summary["variants_total"] = float(len(structural))
            scores = [entry.get("best_vina_score") for entry in structural.values()
                      if isinstance(entry, dict) and entry.get("best_vina_score") is not None]
            if scores:
                summary["best_affinity_global"] = float(min(scores))
        if isinstance(vina, dict):
            summary["docking_targets"] = float(len(vina))
        if isinstance(manifest_data, dict) and isinstance(manifest_data.get("files"), list):
            summary["published_files"] = float(len(manifest_data["files"]))

        artifacts = [path for path in (args.params, args.images, args.run_manifest,
                                       args.structural_metrics, args.vina_affinities)
                     if path and Path(path).is_file()]
        artifacts.extend(path for path in args.artifact if Path(path).is_file())

        stage_params = {
            "ingest": {},
            "fasta": {},
            "structures": {},
            "docking": {},
            "publish": {},
        }
        stage_metrics: dict[str, dict[str, float]] = {
            "ingest": {},
            "fasta": {},
            "structures": {},
            "docking": {},
            "metrics": {},
            "publish": {},
        }

        if isinstance(structural, dict):
            for variant, entry in structural.items():
                if not isinstance(entry, dict):
                    continue
                for field in ("wt_plddt", "mut_plddt"):
                    if entry.get(field) is not None:
                        stage_metrics["structures"][metric_name(variant, field)] = float(entry[field])
                for field in ("rmsd_global", "rmsd_active"):
                    if entry.get(field) is not None:
                        stage_metrics["metrics"][metric_name(variant, field)] = float(entry[field])
                if entry.get("best_vina_score") is not None:
                    stage_metrics["metrics"][metric_name(variant, "best_vina_score")] = float(
                        entry["best_vina_score"])

        if isinstance(vina, dict):
            for variant, scores in vina.items():
                if not isinstance(scores, dict) or not scores:
                    continue
                for drug, value in scores.items():
                    if value is None:
                        continue
                    stage_metrics["docking"][metric_name(variant, drug, "affinity")] = float(value)
                stage_metrics["docking"][metric_name(variant, "best_affinity")] = float(
                    min(float(v) for v in scores.values() if v is not None))

        data_dir = Path(args.data_dir) if args.data_dir else None
        source_code_dir = Path(args.source_code_dir)
        if not source_code_dir.is_dir():
            die(f"no existe el snapshot de código: {source_code_dir}")

        stage_artifacts: dict[str, list[str]] = {
            "ingest": [],
            "fasta": [],
            "structures": [],
            "docking": [],
            "metrics": [],
            "publish": [path for path in (args.run_manifest, args.params) if path and Path(path).is_file()],
        }

        if data_dir and data_dir.is_dir():
            for name in ("top_variants.json", "raw_mutations.json", "mutation_stats.json",
                         "contract_provenance.json", "data_ingest.json"):
                p = data_dir / name
                if p.is_file():
                    stage_artifacts["ingest"].append(str(p))
                    if name == "contract_provenance.json":
                        artifacts.append(str(p))

            p_struct = data_dir / "structures"
            if p_struct.is_dir():
                stage_artifacts["structures"].append(str(p_struct))
            p_man = data_dir / "manifest_structures.json"
            if p_man.is_file():
                stage_artifacts["structures"].append(str(p_man))

            p_dock = data_dir / "docking"
            if p_dock.is_dir():
                stage_artifacts["docking"].append(str(p_dock))

            p_met = data_dir / "structural_metrics.json"
            if p_met.is_file():
                stage_artifacts["metrics"].append(str(p_met))

        # Registrar Datasets oficiales (MLflow 2.x log_input)
        stage_datasets: dict[str, object] = {}
        try:
            import mlflow.data
            import pandas as pd
            study = params_data.get("study_id", "brca_tcga")
            if data_dir and (data_dir / "top_variants.json").is_file():
                top_df = pd.read_json(str(data_dir / "top_variants.json"))
                ingest_ds = mlflow.data.from_pandas(
                    top_df,
                    source=f"https://www.cbioportal.org/study/summary?id={study}",
                    name=f"cBioPortal-{study}-variants",
                )
                stage_datasets["ingest"] = ingest_ds
        except Exception:
            pass

        # El padre debe estar activo para crear hijas anidadas, incluso si ya
        # existía (start_run por run_id lo reabre sin duplicarlo).
        registered: dict[str, dict] = {}
        with mlflow.start_run(run_id=parent_id):
            if summary:
                mlflow.log_metrics(summary)
            for artifact in artifacts:
                mlflow.log_artifact(str(artifact), artifact_path="contracts")
            for stage in STAGES:
                run_id, created = log_stage(
                    mlflow, client, experiment_id, run_name, stage,
                    stage_params.get(stage, {}), stage_metrics.get(stage, {}),
                    stage_artifacts.get(stage, []), base_tags,
                    source_code_dir=source_code_dir,
                    dataset=stage_datasets.get(stage),
                )
                registered[stage] = {"run_id": run_id, "created": created}

    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — mensaje único, resultados ya publicados
        die(
            f"no se pudo registrar en MLflow ({args.tracking_uri}, experimento "
            f"{args.experiment}): {type(exc).__name__}: {exc}. "
            "Los resultados de la corrida ya fueron publicados; revisa el servidor "
            "y vuelve a ejecutar LOG_MLFLOW."
        )

    record = {
        "tracking_uri": args.tracking_uri,
        "experiment": args.experiment,
        "experiment_id": experiment_id,
        "parent_run_id": parent_id,
        "parent_created": created_parent,
        "stages": registered,
    }
    if args.out:
        write_json(args.out, record, sort_keys=True)
    created = sum(1 for stage in registered.values() if stage["created"])
    print(f"OK MLflow: experimento {args.experiment} ({experiment_id}), "
          f"run {parent_id} ({'nuevo' if created_parent else 'reutilizado'}), "
          f"{created}/{len(registered)} etapas nuevas -> {args.tracking_uri}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
