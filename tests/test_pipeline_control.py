from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))

import pipeline_control_api as control  # noqa: E402


def test_v3_estimate_uses_selected_genes_and_drug_catalog():
    params, summary = control.validate_config({
        "pipeline": "tcga-v3",
        "genes": ["PIK3CA"],
        "max_variants": 2,
        "exhaustiveness": 1,
        "num_modes": 3,
        "vina_timeout_sec": 1200,
        "max_parallel_vina": 2,
        "box_size": 25,
        "vina_seed": 42,
    })
    assert params["genes"] == "PIK3CA"
    assert summary["variant_count_estimate"] == 2
    assert summary["wild_type_receptors_estimate"] == 1
    assert summary["receptor_count_estimate"] == 3
    assert summary["drug_count_estimate"] == 11
    assert summary["docking_pairs_estimate"] == 33
    assert summary["estimate"]["total_seconds_high"] >= summary["estimate"]["docking_seconds_high"]
    effective = summary["effective_config"]
    assert effective["workflow_file"] == "main_v3.nf"
    assert effective["profile"] == "docker,gemamx-net,v3-tcga-hispanic"
    assert effective["params"]["clinical_ingest"] is True
    assert effective["processes"]["RUN_VINA"]["nextflow_timeout_seconds"] == 1500


def test_rejects_gene_outside_selected_pipeline():
    with pytest.raises(ValueError, match="Genes no permitidos"):
        control.validate_config({"pipeline": "tcga-v3", "genes": ["MYC"]})


def test_command_uses_only_configured_workflow_and_profile(tmp_path: Path):
    pipeline = control.PIPELINES["tcga-v3"]
    command = control.build_command(
        "web_20261108_120000",
        pipeline,
        tmp_path / "params.json",
        tmp_path / "trace.tsv",
        resume=True,
    )
    assert command[command.index("-profile") + 1] == pipeline["profile"]
    assert command[command.index("-name") + 1] == "web_20261108_120000"
    assert str(ROOT / "main_v3.nf") in command
    assert "-resume" in command
    assert "shell" not in command


def test_duration_parser_handles_nextflow_units():
    assert control.duration_seconds("1h 2m 3.5s") == 3723.5
    assert control.duration_seconds("invalid") is None
