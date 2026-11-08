#!/usr/bin/env python3
"""Create and finalize the parent MLflow run for the V3 wrapper."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def get_client(tracking_uri: str):
    try:
        import mlflow
        from mlflow import MlflowClient
    except ImportError as exc:
        raise RuntimeError("MLflow no está instalado en la imagen") from exc
    mlflow.set_tracking_uri(tracking_uri)
    return MlflowClient(tracking_uri=tracking_uri)


def get_experiment(client, name: str) -> str:
    experiment = client.get_experiment_by_name(name)
    if experiment is None:
        return client.create_experiment(name, artifact_location="mlflow-artifacts:/")
    return experiment.experiment_id


def find_parent(client, experiment_id: str, run_name: str):
    runs = client.search_runs(
        experiment_ids=[experiment_id],
        filter_string=f"tags.\"gemamx.run_name\" = '{run_name}'",
        max_results=100,
        order_by=["attributes.start_time DESC"],
    )
    return next((run for run in runs if not run.data.tags.get("gemamx.stage")), None)


def flatten_params(data: object, prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}

    def walk(value: object, key: str) -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, f"{key}.{child_key}" if key else str(child_key))
        elif isinstance(value, (list, tuple)):
            flat[key[:250]] = ",".join(str(item) for item in value)[:500]
        elif value is not None:
            flat[key[:250]] = str(value).lower() if isinstance(value, bool) else str(value)[:500]

    walk(data, prefix)
    return flat


def start_run(client, experiment_id: str, run_name: str, git_commit: str,
              workflow_file: str, manifest_path: Path | None,
              params_path: Path | None) -> str:
    run = find_parent(client, experiment_id, run_name)
    if run is None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path else {}
        effective = json.loads(params_path.read_text(encoding="utf-8")) if params_path else {}
        effective_params = effective.get("params") or {}
        cohort = manifest.get("cohort") or {}
        counts = manifest.get("counts") or {}
        tags = {
            "mlflow.runName": run_name,
            "gemamx.pipeline": "gemamx_nf",
            "gemamx.run_name": run_name,
            "gemamx.git_commit": git_commit or "unknown",
            "gemamx.workflow_file": workflow_file,
            "gemamx.status": "RUNNING",
        }
        if manifest.get("bundle_id"):
            tags["gemamx.bundle_id"] = str(manifest["bundle_id"])
        run = client.create_run(experiment_id, tags=tags)
        run_id = run.info.run_id
        params = {
            "pipeline_version": effective.get("pipeline_label", workflow_file),
            "workflow_file": workflow_file,
            "study_id": effective.get("study_id", effective_params.get("study_id", manifest.get("dataset_id", "unknown"))),
            "cohort_total_cases": cohort.get("total_cases", counts.get("cohort_cases")),
            "cohort_cases_with_mutations": cohort.get("cases_with_mutations", counts.get("mutation_patients")),
            "mutation_records": counts.get("mutation_records"),
            "gdc_data_release": manifest.get("gdc_data_release"),
        }
        for key, value in params.items():
            if value is not None:
                client.log_param(run_id, key, str(value))
        if params_path:
            for key, value in flatten_params(effective, "effective").items():
                client.log_param(run_id, key, value)
            client.log_artifact(run_id, str(params_path), artifact_path="execution_config")
            client.set_tag(run_id, "gemamx.execution_config", "execution_config/" + params_path.name)
    else:
        run_id = run.info.run_id
        client.set_tag(run_id, "gemamx.status", "RUNNING")
        if params_path:
            effective = json.loads(params_path.read_text(encoding="utf-8"))
            for key, value in flatten_params(effective, "effective").items():
                client.log_param(run_id, key, value)
            client.log_artifact(run_id, str(params_path), artifact_path="execution_config")
            client.set_tag(run_id, "gemamx.execution_config", "execution_config/" + params_path.name)
    return run_id


def finish_run(client, experiment_id: str, run_name: str, status: str,
               exit_code: int) -> str:
    run = find_parent(client, experiment_id, run_name)
    if run is None:
        raise RuntimeError(f"no existe el run MLflow {run_name}")
    terminal_status = "FAILED" if status == "failed" else "FINISHED"
    client.set_tag(run.info.run_id, "gemamx.status", terminal_status)
    client.set_tag(run.info.run_id, "gemamx.exit_code", str(exit_code))
    client.set_terminated(run.info.run_id, status=terminal_status)
    return run.info.run_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Gestiona el run padre de un pipeline GEMAMX")
    parser.add_argument("action", choices=("start", "finish"))
    parser.add_argument("--tracking-uri", required=True)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--git-commit", default="")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--params-json", type=Path)
    parser.add_argument("--workflow-file", default="main_v3.nf")
    parser.add_argument("--status", choices=("completed", "failed"))
    parser.add_argument("--exit-code", type=int, default=0)
    args = parser.parse_args()

    try:
        client = get_client(args.tracking_uri)
        experiment_id = get_experiment(client, args.experiment)
        if args.action == "start":
            run_id = start_run(client, experiment_id, args.run_name,
                               args.git_commit, args.workflow_file,
                               args.manifest, args.params_json)
        else:
            if args.status is None:
                raise ValueError("--status es obligatorio al finalizar el run")
            run_id = finish_run(client, experiment_id, args.run_name,
                                args.status, args.exit_code)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"{experiment_id}\t{run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())