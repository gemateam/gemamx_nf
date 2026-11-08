#!/usr/bin/env python3
"""Import TCGA-BRCA V1 raw data without running structure or docking tasks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GENES = "PIK3CA,TP53,ERBB2,BRCA1,BRCA2,CDH1,GATA3,MAP3K1,KMT2C,PTEN,RB1,ARID1A,SF3B1,AKT1,CBFB"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str]) -> str:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def register_mlflow(run_name: str, config_path: Path, params: dict) -> str:
    command = [
        "docker", "run", "--rm", "--network", "gemamx_net",
        "-v", f"{ROOT}:/workspace:ro", "-w", "/workspace",
        "gemamx-cpu:1.0.0", "python3", "/workspace/bin/manage_mlflow_run.py",
        "start", "--tracking-uri", "http://gemamx_mlflow:5000",
        "--experiment", "GEMAMX-V1-NF", "--run-name", run_name,
        "--workflow-file", "main.nf", "--params-json",
        f"/workspace/{config_path.relative_to(ROOT).as_posix()}",
    ]
    result = run(command)
    id_line = next((line for line in reversed(result.splitlines()) if "\t" in line), "")
    fields = id_line.split("\t")
    if len(fields) != 2:
        raise RuntimeError(f"respuesta inesperada de MLflow: {result[-300:]}")
    experiment_id, run_id = fields

    for artifact in ("raw_mutations.json", "top_variants.json", "mutation_stats.json", "data_ingest.json"):
        path = config_path.parent / "data" / artifact
        artifact_command = [
            "docker", "run", "--rm", "--network", "gemamx_net",
            "-v", f"{ROOT}:/workspace:ro", "-w", "/workspace",
            "gemamx-cpu:1.0.0", "python3", "-c",
            "import sys,mlflow; from mlflow import MlflowClient; mlflow.set_tracking_uri('http://gemamx_mlflow:5000'); c=MlflowClient(tracking_uri='http://gemamx_mlflow:5000'); c.log_artifact(sys.argv[2], sys.argv[1], artifact_path='import')",
            f"/workspace/{path.relative_to(ROOT).as_posix()}",
            run_id,
        ]
        run(artifact_command)

    finish_command = [
        "docker", "run", "--rm", "--network", "gemamx_net",
        "-v", f"{ROOT}:/workspace:ro", "-w", "/workspace",
        "gemamx-cpu:1.0.0", "python3", "/workspace/bin/manage_mlflow_run.py",
        "finish", "--tracking-uri", "http://gemamx_mlflow:5000",
        "--experiment", "GEMAMX-V1-NF", "--run-name", run_name,
        "--workflow-file", "main.nf", "--params-json",
        f"/workspace/{config_path.relative_to(ROOT).as_posix()}",
        "--status", "completed", "--exit-code", "0",
    ]
    run(finish_command)
    return experiment_id, run_id


def update_index(run_name: str, published_at: str, git_commit: str) -> None:
    path = ROOT / "results" / "runs" / "index.json"
    index = []
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                index = [row for row in loaded if isinstance(row, dict)]
        except json.JSONDecodeError:
            index = []
    index = [row for row in index if row.get("run_name") != run_name]
    index.insert(0, {
        "run_name": run_name,
        "published_at": published_at,
        "git_commit": git_commit[:7],
        "path": f"runs/{run_name}/data",
        "pipeline_version": "GEMAMX-V1-NF",
        "description": "Importación cBioPortal V1 sin estructuras ni docking",
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Importa datos crudos de TCGA-BRCA V1 sin ejecutar docking")
    parser.add_argument("--study", default="brca_tcga")
    parser.add_argument("--genes", default=DEFAULT_GENES)
    parser.add_argument("--max-variants", type=int, default=20)
    parser.add_argument("--run-name", help="nombre para finalizar una importación parcial existente")
    parser.add_argument("--reuse-existing", action="store_true",
                        help="reutiliza raw_mutations/data_ingest existentes sin llamar otra vez a cBioPortal")
    args = parser.parse_args()
    if args.max_variants < 1:
        parser.error("--max-variants debe ser positivo")

    run_name = args.run_name or f"v1_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if not re.fullmatch(r"[A-Za-z0-9._-]+", run_name):
        parser.error("--run-name contiene caracteres no admitidos")
    run_dir = ROOT / "results" / "runs" / run_name
    data_dir = run_dir / "data"
    if run_dir.exists():
        if not args.reuse_existing:
            parser.error(f"ya existe {run_dir}; usa --reuse-existing para finalizar la importación")
        if not (data_dir / "raw_mutations.json").is_file() or not (data_dir / "data_ingest.json").is_file():
            parser.error(f"{data_dir} no contiene una importación completa para reutilizar")
    else:
        data_dir.mkdir(parents=True, exist_ok=False)
    params = {
        "study_id": args.study,
        "genes": args.genes,
        "max_variants": args.max_variants,
        "mutations_json": None,
        "import_only": True,
        "mlflow_experiment": "GEMAMX-V1-NF",
    }

    try:
        if not args.reuse_existing:
            run([
                sys.executable, str(ROOT / "bin" / "ingest_cbioportal.py"),
                "--study", args.study,
                "--genes", args.genes,
                "--max-variants", str(args.max_variants),
                "--outdir", str(data_dir),
            ])
        ingestion = json.loads((data_dir / "data_ingest.json").read_text(encoding="utf-8"))
        total_samples = int(ingestion["counts"]["cohort_units"])
        if not (data_dir / "mutation_stats.json").is_file():
            run([
                sys.executable, str(ROOT / "bin" / "build_stats.py"),
                "--raw", str(data_dir / "raw_mutations.json"),
                "--out", str(data_dir / "mutation_stats.json"),
                "--total-samples", str(total_samples),
            ])
        (data_dir / "structural_metrics.json").write_text("{}\n", encoding="utf-8")
        (data_dir / "manifest_structures.json").write_text("{}\n", encoding="utf-8")
        (data_dir / "docking").mkdir(exist_ok=True)
        (data_dir / "docking" / "vina_affinities.json").write_text("{}\n", encoding="utf-8")

        git_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT,
            capture_output=True, text=True,
        ).stdout.strip() or "unknown"
        published_at = utc_now()
        manifest = {
            "run_name": run_name,
            "pipeline_version": "GEMAMX-V1-NF",
            "published_at": published_at,
            "git_commit": git_commit,
            "import_only": True,
            "params": params,
            "images": {"image_cpu": "gemamx-cpu:1.0.0"},
            "contracts": ["raw_mutations.json", "top_variants.json", "mutation_stats.json", "data_ingest.json"],
            "files": {path.name: sha256(path) for path in data_dir.glob("*.json")},
        }
        (run_dir / "run_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (data_dir / "run_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        config_path = run_dir / "execution_config.json"
        config_path.write_text(json.dumps({"pipeline_label": "TCGA-BRCA V1 import-only", **params,
                                           "query": ingestion["query"]}, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        experiment_id, run_id = register_mlflow(run_name, config_path, params)
        manifest["experiment_id"] = experiment_id
        manifest["parent_run_id"] = run_id
        (run_dir / "run_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (data_dir / "run_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        update_index(run_name, published_at, git_commit)
        print(json.dumps({"run_name": run_name, "run_id": run_id, "experiment_id": experiment_id,
                          "cases": total_samples, "raw_mutations": ingestion["counts"]["raw_mutation_records"],
                          "data_ingest": ingestion["query"]}, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: importación V1 fallida; no se modificó results/data: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
