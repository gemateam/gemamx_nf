#!/usr/bin/env python3
"""Tests for stage-specific source snapshots and MLflow artifact logging."""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_WORKFLOWS = {"main.nf", "main_v2.nf", "main_v2_1.nf"}
import sys
sys.path.insert(0, str(ROOT / "bin"))

import log_mlflow  # noqa: E402
from snapshot_mlflow_sources import snapshot_sources  # noqa: E402


class FakeClient:
    def __init__(self, existing=None, search_results=None):
        self.existing = existing
        self.search_results = search_results
        self.tags = {}
        self.deleted = []
        self.artifacts = []

    def search_runs(self, **_kwargs):
        if self.search_results is not None:
            return self.search_results
        return [self.existing] if self.existing else []

    def set_tag(self, run_id, key, value):
        self.tags[(run_id, key)] = value

    def delete_tag(self, run_id, key):
        self.deleted.append((run_id, key))

    def log_artifacts(self, run_id, local_dir, artifact_path=None):
        self.artifacts.append((run_id, Path(local_dir), artifact_path))


class FakeMlflow:
    def __init__(self):
        self.active_run = None
        self.tags = {}
        self.artifacts = []

    @contextmanager
    def start_run(self, run_name=None, experiment_id=None, nested=False, tags=None, run_id=None):
        identifier = run_id or "new-stage-run"
        self.active_run = identifier
        self.tags.update(tags or {})
        try:
            yield SimpleNamespace(info=SimpleNamespace(run_id=identifier))
        finally:
            self.active_run = None

    def log_artifacts(self, local_dir, artifact_path=None):
        self.artifacts.append((self.active_run, Path(local_dir), artifact_path))

    def log_params(self, _params):
        pass

    def log_metrics(self, _metrics):
        pass


class ExistingRun:
    def __init__(self, run_id, stage=None):
        self.info = SimpleNamespace(run_id=run_id)
        tags = {"gemamx.stage": stage} if stage else {}
        self.data = SimpleNamespace(tags=tags)


def test_parent_lookup_skips_child_runs() -> None:
    child = ExistingRun("child-run", stage="publish")
    parent = ExistingRun("parent-run")
    client = FakeClient(search_results=[child, parent])
    assert log_mlflow.find_run(client, "4", "run-v1", None) is parent


def test_snapshots_cover_supported_workflows(tmp: Path) -> None:
    for workflow in ("main.nf", "main_v2.nf", "main_v2_1.nf"):
        output = tmp / workflow
        manifest = snapshot_sources(ROOT, output, workflow, "a" * 40)
        assert set(manifest["stages"]) == set(log_mlflow.STAGES)
        for stage, detail in manifest["stages"].items():
            stage_dir = output / stage
            assert (stage_dir / "source_manifest.json").is_file()
            assert all((stage_dir / path).is_file() for path in detail["files"])
            assert detail["git_commit"] == "a" * 40


def test_workflows_enforce_mlflow_code_and_report_contract() -> None:
    entrypoints = {path.name for path in ROOT.glob("main*.nf")}
    assert entrypoints == PIPELINE_WORKFLOWS

    for workflow in sorted(PIPELINE_WORKFLOWS):
        text = (ROOT / workflow).read_text(encoding="utf-8")
        assert "snapshot_mlflow_sources.py" in text
        assert f"'--workflow', '{workflow}'" in text
        assert "def ch_source_snapshot = Channel.value(source_snapshot)" in text
        log_call = text.split("LOG_MLFLOW(", 1)[1].split("\n    )", 1)[0]
        assert "ch_source_snapshot" in log_call
        completion = text.split("workflow.onComplete", 1)[1]
        assert "nf_reports_hook.sh" in completion
        assert "--run-name" in completion
        assert "--experiment" in completion

    nextflow_config = (ROOT / "nextflow.config").read_text(encoding="utf-8")
    for report in ("report.html", "timeline.html", "trace.tsv", "dag.html"):
        assert report in nextflow_config

    upload_hook = (ROOT / "bin" / "nf_reports_hook.sh").read_text(encoding="utf-8")
    uploader = (ROOT / "bin" / "upload_nf_reports.py").read_text(encoding="utf-8")
    assert "upload_nf_reports.py" in upload_hook
    assert 'NF_REPORT_FILES = ["report.html", "timeline.html", "dag.html"]' in uploader
    assert 'artifact_path="nextflow_reports"' in uploader


def test_new_stage_logs_code_as_artifact(tmp: Path) -> None:
    source_dir = tmp / "sources"
    snapshot_sources(ROOT, source_dir, "main.nf", "a" * 40)
    mlflow, client = FakeMlflow(), FakeClient()
    run_id, created = log_mlflow.log_stage(
        mlflow, client, "4", "run-v1", "ingest", {}, {}, [],
        {"gemamx.run_name": "run-v1"}, source_dir,
    )
    assert created and run_id == "new-stage-run"
    run_id, local_dir, artifact_path = mlflow.artifacts[-1]
    assert run_id == "new-stage-run"
    assert local_dir == source_dir / "ingest"
    assert artifact_path == "source_code"
    assert "gemamx.source_code_artifact" in mlflow.tags
    assert not any("github.com" in value for value in mlflow.tags.values())


def test_existing_stage_is_backfilled_and_legacy_links_removed(tmp: Path) -> None:
    source_dir = tmp / "sources"
    snapshot_sources(ROOT, source_dir, "main.nf", "b" * 40)
    mlflow = FakeMlflow()
    existing = ExistingRun("existing-ingest")
    client = FakeClient(existing)
    run_id, created = log_mlflow.log_stage(
        mlflow, client, "4", "run-v1", "ingest", {}, {}, [],
        {"gemamx.run_name": "run-v1"}, source_dir,
    )
    assert not created and run_id == "existing-ingest"
    assert client.artifacts[-1] == ("existing-ingest", source_dir / "ingest", "source_code")
    assert ("existing-ingest", "gemamx.source_code") in client.deleted
    assert ("existing-ingest", "mlflow.source.name") in client.deleted
    assert client.tags[("existing-ingest", "gemamx.source_code_artifact")] == "source_code"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="gemamx-mlflow-source-test-") as temp:
        root = Path(temp)
        test_snapshots_cover_supported_workflows(root)
        test_workflows_enforce_mlflow_code_and_report_contract()
        test_parent_lookup_skips_child_runs()
        test_new_stage_logs_code_as_artifact(root)
        test_existing_stage_is_backfilled_and_legacy_links_removed(root)
    print("OK: source snapshots and MLflow artifacts")


if __name__ == "__main__":
    main()
