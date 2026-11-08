from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))

from manage_mlflow_run import finish_run, start_run  # noqa: E402


class FakeClient:
    def __init__(self):
        self.run = None
        self.params = {}
        self.tags = {}
        self.terminal_status = None
        self.artifacts = []

    def search_runs(self, **kwargs):
        return [self.run] if self.run else []

    def create_run(self, experiment_id, tags):
        self.tags.update(tags)
        self.run = SimpleNamespace(
            info=SimpleNamespace(run_id="parent-1", experiment_id=experiment_id),
            data=SimpleNamespace(tags=self.tags),
        )
        return self.run

    def log_param(self, run_id, key, value):
        self.params[key] = value

    def set_tag(self, run_id, key, value):
        self.tags[key] = value

    def set_terminated(self, run_id, status):
        self.terminal_status = status

    def log_artifact(self, run_id, local_path, artifact_path=None):
        self.artifacts.append((run_id, Path(local_path).name, artifact_path))


def test_effective_config_is_logged_before_run_finishes(tmp_path: Path):
    config = tmp_path / "effective.json"
    config.write_text(
        '{"pipeline":"tcga-v3","profile":"docker,gemamx-net,v3-tcga-hispanic",'
        '"params":{"genes":"PIK3CA,TP53","max_variants":3,"vina_timeout_sec":900}}',
        encoding="utf-8",
    )
    client = FakeClient()
    run_id = start_run(client, "8", "web_20261108_120000", "abc123",
                       "main_v3.nf", None, config)
    assert run_id == "parent-1"
    assert client.tags["gemamx.status"] == "RUNNING"
    assert client.params["effective.pipeline"] == "tcga-v3"
    assert client.params["effective.params.max_variants"] == "3"
    assert client.params["effective.params.vina_timeout_sec"] == "900"
    assert client.artifacts == [("parent-1", "effective.json", "execution_config")]
    assert client.tags["gemamx.execution_config"] == "execution_config/effective.json"

    finish_run(client, "8", "web_20261108_120000", "failed", 1)
    assert client.tags["gemamx.status"] == "FAILED"
    assert client.terminal_status == "FAILED"
