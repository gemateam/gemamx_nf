from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))

import ingest_cbioportal  # noqa: E402


def test_cbioportal_http_query_is_recorded(monkeypatch):
    ingest_cbioportal.REQUEST_LOG.clear()
    payload = {"sampleIds": ["TCGA-AA-0001-01A", "TCGA-AA-0002-01A"]}

    def fake_request(method, url, json, timeout):
        assert method == "POST"
        assert url.endswith("/molecular-profiles/brca_tcga_mutations/mutations/fetch")
        assert json == payload
        return SimpleNamespace(status_code=200, json=lambda: [{"hugoGeneSymbol": "PIK3CA"}])

    monkeypatch.setattr(ingest_cbioportal.requests, "request", fake_request)
    result = ingest_cbioportal.http_json(
        "POST",
        "https://www.cbioportal.org/api/molecular-profiles/brca_tcga_mutations/mutations/fetch",
        payload,
    )

    assert len(result) == 1
    assert ingest_cbioportal.REQUEST_LOG == [{
        "method": "POST",
        "url": "https://www.cbioportal.org/api/molecular-profiles/brca_tcga_mutations/mutations/fetch",
        "request": payload,
        "response_records": 1,
    }]


def test_ingestion_metadata_reaches_each_pipeline_contract():
    for workflow in ("main.nf", "main_v2.nf", "main_v2_1.nf", "main_v3.nf"):
        text = (ROOT / workflow).read_text(encoding="utf-8")
        assert "BUILD_JSONS.out.data_ingest_out" in text
        if workflow in ("main.nf", "main_v3.nf"):
            assert "INGEST.out.ingest_metadata" in text
        else:
            assert "INGEST_ROMERO.out.ingest_metadata" in text

    metrics_module = (ROOT / "modules" / "metrics" / "main.nf").read_text(encoding="utf-8")
    assert 'path "stage/data/data_ingest.json"' in metrics_module
    build_jsons = (ROOT / "bin" / "build_jsons.py").read_text(encoding="utf-8")
    assert build_jsons.count('"data_ingest.json"') >= 2
