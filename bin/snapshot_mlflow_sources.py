#!/usr/bin/env python3
"""Snapshot the source files associated with each MLflow pipeline stage."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


STAGE_FILES = {
    "ingest": {
        "main.nf": {
            "primary": "bin/ingest_cbioportal.py",
            "files": ["modules/ingest/main.nf", "bin/ingest_cbioportal.py", "bin/build_stats.py"],
        },
        "main_v2.nf": {
            "primary": "bin/ingest_romero.py",
            "files": ["modules/clinical/main.nf", "bin/ingest_romero.py", "bin/extract_clinical_romero.py", "bin/build_clinical_summary.py"],
        },
        "main_v2_1.nf": {
            "primary": "bin/ingest_romero.py",
            "files": ["modules/clinical/main.nf", "bin/ingest_romero.py", "bin/extract_clinical_romero.py", "bin/build_clinical_summary.py"],
        },
        "main_v3.nf": {
            "primary": "bin/ingest_cbioportal.py",
            "files": ["modules/ingest/main.nf", "bin/ingest_cbioportal.py", "bin/build_stats.py"],
        },
    },
    "fasta": {
        "main.nf": {
            "primary": "bin/fetch_fasta.py",
            "files": ["modules/fasta/main.nf", "bin/fetch_fasta.py"],
        },
        "main_v2.nf": {
            "primary": "bin/fetch_fasta.py",
            "files": ["modules/fasta/main.nf", "bin/fetch_fasta.py"],
        },
        "main_v2_1.nf": {
            "primary": "bin/fetch_fasta.py",
            "files": ["modules/fasta/main.nf", "bin/fetch_fasta.py"],
        },
        "main_v3.nf": {
            "primary": "bin/fetch_fasta.py",
            "files": ["modules/fasta/main.nf", "bin/fetch_fasta.py"],
        },
    },
    "structures": {
        "main.nf": {
            "primary": "bin/predict_structure.py",
            "files": ["modules/structure/main.nf", "bin/predict_structure.py"],
        },
        "main_v2.nf": {
            "primary": "bin/predict_structure.py",
            "files": ["modules/structure/main.nf", "bin/predict_structure.py"],
        },
        "main_v2_1.nf": {
            "primary": "bin/predict_structure.py",
            "files": ["modules/structure/main.nf", "modules/structure/v2_1.nf", "bin/predict_structure.py"],
        },
        "main_v3.nf": {
            "primary": "bin/predict_structure.py",
            "files": ["modules/structure/main.nf", "bin/predict_structure.py"],
        },
    },
    "docking": {
        workflow: {
            "primary": "bin/run_vina.py",
            "files": ["modules/docking/main.nf", "bin/prep_ligand.py", "bin/prep_receptor.py", "bin/dock_center.py", "bin/run_vina.py", "bin/merge_pose.py"],
        }
        for workflow in ("main.nf", "main_v2.nf", "main_v2_1.nf", "main_v3.nf")
    },
    "metrics": {
        workflow: {
            "primary": "bin/build_jsons.py",
            "files": ["modules/metrics/main.nf", "bin/align_wt_mut.py", "bin/build_jsons.py", "bin/build_manifest.py"],
        }
        for workflow in ("main.nf", "main_v2.nf", "main_v2_1.nf", "main_v3.nf")
    },
    "publish": {
        workflow: {
            "primary": "bin/publish_results.py",
            "files": ["modules/metrics/main.nf", "modules/mlflow/main.nf", "bin/publish_results.py", "bin/log_mlflow.py"],
        }
        for workflow in ("main.nf", "main_v2.nf", "main_v2_1.nf", "main_v3.nf")
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def snapshot_sources(repo_root: Path, output_dir: Path, workflow_file: str, commit: str) -> dict:
    if workflow_file not in {"main.nf", "main_v2.nf", "main_v2_1.nf", "main_v3.nf"}:
        raise ValueError(f"workflow no soportado: {workflow_file}")

    repo_root = repo_root.resolve()
    if not (repo_root / workflow_file).is_file():
        raise FileNotFoundError(repo_root / workflow_file)

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    stages = {}
    for stage, workflows in STAGE_FILES.items():
        spec = workflows[workflow_file]
        stage_dir = output_dir / stage
        stage_dir.mkdir()
        selected = list(dict.fromkeys([workflow_file, *spec["files"]]))
        files = {}
        for relative in selected:
            source = repo_root / relative
            if not source.is_file():
                raise FileNotFoundError(source)
            destination = stage_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            files[relative] = sha256(destination)

        stage_manifest = {
            "stage": stage,
            "workflow": workflow_file,
            "primary_source": spec["primary"],
            "git_commit": commit or "unknown",
            "files": files,
        }
        (stage_dir / "source_manifest.json").write_text(
            json.dumps(stage_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        stages[stage] = stage_manifest

    manifest = {
        "workflow": workflow_file,
        "git_commit": commit or "unknown",
        "stages": stages,
    }
    (output_dir / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Snapshot pipeline sources for MLflow stages")
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--git-commit", default="")
    args = parser.parse_args()

    manifest = snapshot_sources(args.repo, args.out, args.workflow, args.git_commit)
    print(f"OK source snapshot: {manifest['workflow']} ({len(manifest['stages'])} stages) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
