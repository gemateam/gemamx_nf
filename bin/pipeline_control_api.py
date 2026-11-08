#!/usr/bin/env python3
"""Local control API for launching allow-listed Nextflow pipelines."""

from __future__ import annotations

import csv
import json
import math
import os
import re
import signal
import statistics
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
LIVE_DIR = ROOT / "results" / "runs" / "_live"
STATUS_PATH = LIVE_DIR / "status.json"
PORT = 8765
ALLOWED_ORIGINS = {"http://localhost:8080", "http://127.0.0.1:8080"}
MLFLOW_URI = "http://gemamx_mlflow:5000"
MLFLOW_IMAGE = "gemamx-cpu:1.0.0"
DOCKER_NETWORK = "gemamx_net"
START_LOCK = threading.Lock()
CURRENT_PROCESS: subprocess.Popen | None = None

PIPELINES = {
    "tcga-v1": {
        "label": "TCGA-BRCA V1",
        "workflow": "main.nf",
        "study_id": "brca_tcga",
        "profile": "docker,gemamx-net",
        "experiment": "GEMAMX-V1-NF",
        "genes": ["PIK3CA", "TP53", "ERBB2", "BRCA1", "BRCA2", "CDH1", "GATA3", "MAP3K1", "KMT2C", "PTEN", "RB1", "ARID1A", "SF3B1", "AKT1", "CBFB"],
        "max_variants_limit": 50,
        "defaults": {"genes": ["PIK3CA", "TP53"], "max_variants": 3, "exhaustiveness": 1, "num_modes": 3, "vina_timeout_sec": 900, "max_parallel_vina": 4, "box_size": 25, "vina_seed": 42},
        "variant_file": "tests/reference/legacy/top_variants.json",
        "target_drug_map": None,
    },
    "romero-v2": {
        "label": "Romero-Cordoba V2",
        "workflow": "main_v2.nf",
        "study_id": "romero_fucam_hm",
        "profile": "docker,gemamx-net,romero-v2",
        "experiment": "GEMAMX-V2-ROMERO",
        "genes": ["PIK3CA", "TP53", "AKT1", "ERBB2", "PTEN", "GATA3", "MAP3K1"],
        "max_variants_limit": 49,
        "defaults": {"genes": ["PIK3CA", "TP53"], "max_variants": 3, "exhaustiveness": 1, "num_modes": 3, "vina_timeout_sec": 900, "max_parallel_vina": 4, "box_size": 25, "vina_seed": 42},
        "variant_file": "tests/reference/romero_v2/top_variants.json",
        "target_drug_map": None,
    },
    "romero-v2_1": {
        "label": "Romero-Cordoba V2.1",
        "workflow": "main_v2_1.nf",
        "study_id": "romero_fucam_hm",
        "profile": "docker,gemamx-net,romero-v2,v2_1",
        "experiment": "GEMAMX-V2_1-ROMERO",
        "genes": ["PIK3CA", "TP53", "AKT1", "ERBB2", "PTEN", "GATA3", "MAP3K1"],
        "max_variants_limit": 49,
        "defaults": {"genes": ["PIK3CA", "TP53"], "max_variants": 3, "exhaustiveness": 1, "num_modes": 3, "vina_timeout_sec": 900, "max_parallel_vina": 4, "box_size": 25, "vina_seed": 42},
        "variant_file": "tests/reference/romero_v2/top_variants.json",
        "target_drug_map": "assets/target_drug_map.csv",
    },
    "tcga-v3": {
        "label": "TCGA-BRCA Hispano/Latino V3",
        "workflow": "main_v3.nf",
        "study_id": "TCGA-BRCA-HISPANIC",
        "profile": "docker,gemamx-net,v3-tcga-hispanic",
        "experiment": "GEMAMX-V3-TCGA-HISPANIC",
        "genes": ["PIK3CA", "TP53", "AKT1", "CDH1", "PTEN", "ESR1", "GATA3", "MAP3K1"],
        "max_variants_limit": 20,
        "defaults": {"genes": ["PIK3CA", "TP53"], "max_variants": 3, "exhaustiveness": 1, "num_modes": 3, "vina_timeout_sec": 900, "max_parallel_vina": 4, "box_size": 25, "vina_seed": 42},
        "variant_file": "tests/reference/tcga_hispanic_v3/somatic_mutations.json",
        "target_drug_map": None,
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def duration_seconds(value: str) -> float | None:
    text = value.strip()
    pattern = re.fullmatch(r"(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+(?:\.\d+)?)\s*s)?", text)
    if not pattern:
        return None
    hours, minutes, seconds = pattern.groups()
    if not any((hours, minutes, seconds)):
        return None
    return int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def variant_count(pipeline_id: str, genes: list[str], maximum: int) -> int:
    pipeline = PIPELINES[pipeline_id]
    path = ROOT / pipeline["variant_file"]
    records = load_json(path, [])
    variants = set()
    for row in records if isinstance(records, list) else []:
        gene = (row.get("hugo_symbol") or row.get("gene") or "").upper()
        change = row.get("protein_change") or ""
        classification = (row.get("variant_classification") or "missense").lower()
        if gene in genes and change and "missense" in classification:
            variants.add((gene, change))
    return min(maximum, len(variants)) if variants else maximum


def analyzed_gene_count(pipeline_id: str, genes: list[str]) -> int:
    pipeline = PIPELINES[pipeline_id]
    records = load_json(ROOT / pipeline["variant_file"], [])
    found = set()
    for row in records if isinstance(records, list) else []:
        gene = (row.get("hugo_symbol") or row.get("gene") or "").upper()
        change = row.get("protein_change") or ""
        if gene in genes and change:
            found.add(gene)
    return len(found) if found else len(genes)


def drug_count(pipeline_id: str, genes: list[str]) -> int:
    pipeline = PIPELINES[pipeline_id]
    target_map = pipeline["target_drug_map"]
    if target_map:
        pairs = set()
        with (ROOT / target_map).open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("gene", "").upper() in genes:
                    pairs.add((row.get("gene", ""), row.get("drug", "")))
        return max(1, len(pairs))
    with (ROOT / "assets" / "drug_catalog.csv").open(encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def historical_vina_durations() -> list[float]:
    traces = sorted(LIVE_DIR.glob("*.trace.tsv"), key=lambda path: path.stat().st_mtime, reverse=True)
    durations = []
    for trace in traces[:20]:
        try:
            with trace.open(encoding="utf-8") as handle:
                headers = handle.readline().rstrip("\r\n").split("\t")
                name_idx, status_idx, duration_idx = (headers.index("name"), headers.index("status"), headers.index("duration"))
                for line in handle:
                    fields = line.rstrip("\r\n").split("\t")
                    if len(fields) <= max(name_idx, status_idx, duration_idx):
                        continue
                    if fields[name_idx].startswith("RUN_VINA") and fields[status_idx] == "COMPLETED":
                        elapsed = duration_seconds(fields[duration_idx])
                        if elapsed is not None and elapsed > 0:
                            durations.append(elapsed)
        except (OSError, ValueError):
            continue
    return durations


def validate_config(payload: dict) -> tuple[dict, dict]:
    pipeline_id = payload.get("pipeline")
    if pipeline_id not in PIPELINES:
        raise ValueError("Selecciona un pipeline disponible.")
    pipeline = PIPELINES[pipeline_id]
    defaults = pipeline["defaults"]
    selected_genes = payload.get("genes", defaults["genes"])
    if isinstance(selected_genes, str):
        selected_genes = [value.strip().upper() for value in selected_genes.split(",") if value.strip()]
    if not isinstance(selected_genes, list) or not selected_genes:
        raise ValueError("Selecciona al menos un gen.")
    selected_genes = list(dict.fromkeys(str(value).upper() for value in selected_genes))
    invalid_genes = sorted(set(selected_genes) - set(pipeline["genes"]))
    if invalid_genes:
        raise ValueError(f"Genes no permitidos para {pipeline['label']}: {', '.join(invalid_genes)}")

    maximum_variants = int(payload.get("max_variants", defaults["max_variants"]))
    if not 1 <= maximum_variants <= pipeline["max_variants_limit"]:
        raise ValueError(f"max_variants debe estar entre 1 y {pipeline['max_variants_limit']}.")
    exhaustiveness = int(payload.get("exhaustiveness", defaults["exhaustiveness"]))
    if not 1 <= exhaustiveness <= 8:
        raise ValueError("exhaustiveness debe estar entre 1 y 8 para esta consola.")
    num_modes = int(payload.get("num_modes", defaults["num_modes"]))
    if not 1 <= num_modes <= 5:
        raise ValueError("num_modes debe estar entre 1 y 5.")
    timeout = int(payload.get("vina_timeout_sec", defaults["vina_timeout_sec"]))
    if not 60 <= timeout <= 14400:
        raise ValueError("El timeout de Vina debe estar entre 60 y 14400 segundos.")
    parallel = int(payload.get("max_parallel_vina", defaults["max_parallel_vina"]))
    if not 1 <= parallel <= 4:
        raise ValueError("max_parallel_vina debe estar entre 1 y 4.")
    box_size = float(payload.get("box_size", defaults["box_size"]))
    if not 10 <= box_size <= 40:
        raise ValueError("box_size debe estar entre 10 y 40 angstroms.")
    seed = int(payload.get("vina_seed", defaults["vina_seed"]))
    if not 0 <= seed <= 2**31 - 1:
        raise ValueError("vina_seed debe estar entre 0 y 2147483647.")

    params = {
        "study_id": pipeline["study_id"],
        "genes": ",".join(selected_genes),
        "max_variants": maximum_variants,
        "exhaustiveness": exhaustiveness,
        "num_modes": num_modes,
        "vina_timeout_sec": timeout,
        "max_parallel_vina": parallel,
        "box_size": box_size,
        "vina_seed": seed,
    }
    profile_params = {
        "disease_type": "Breast Invasive Carcinoma",
        "cohort_ethnicity": None,
        "mutations_json": None,
        "clinical_ingest": False,
        "clinical_json": None,
        "clinical_attributes": "RACE,ETHNICITY,AGE",
        "clinical_small_cell": 5,
        "fasta_dir": None,
        "romero_maf": None,
        "romero_drivers": None,
        "romero_clinical": None,
        "structural_metrics_precomp": None,
        "vina_affinities": None,
        "docking_complex_dir": None,
        "docking_results_dir": None,
        "structures_mode": "precomputed",
        "structures_dir": None,
        "domain_window": 180,
        "boltz_seed": 42,
        "boltz_use_msa_server": True,
        "drug_catalog": "assets/drug_catalog.csv",
        "box_center_mode": "mutation",
        "binding_sites": None,
        "binding_site_name": "ATP_pocket",
        "site_on_missing": "fail",
        "target_drug_map": None,
        "exhaustiveness": pipeline["defaults"]["exhaustiveness"],
        "num_modes": pipeline["defaults"]["num_modes"],
        "box_size": pipeline["defaults"]["box_size"],
        "vina_seed": pipeline["defaults"]["vina_seed"],
        "vina_timeout_sec": pipeline["defaults"]["vina_timeout_sec"],
        "max_parallel_vina": pipeline["defaults"]["max_parallel_vina"],
        "max_variants": pipeline["defaults"]["max_variants"],
        "total_samples": None,
        "contract_dir": None,
        "contract_manifest": None,
        "contract_allow_curated": False,
        "mlflow_tracking_uri": MLFLOW_URI,
        "publish_run_archive": True,
        "outdir": "results",
        "work_dir": "~/gemamx-work",
        "webapp_restart": True,
        "webapp_container": "gemamx_webapp",
        "image_cpu": "gemamx-cpu:1.0.0",
        "image_docking": "gemamx-nf-docking:1.0.0",
        "image_gpu": "gemamx-gpu:1.0.0",
        "image_mlflow": "gemamx-cpu:1.0.0",
        "mlflow_experiment": pipeline["experiment"],
        "mlflow_host_uri": "http://localhost:5000",
        "mlflow_docker_uri": MLFLOW_URI,
        "mlflow_docker_network": DOCKER_NETWORK,
    }
    if pipeline_id == "romero-v2_1":
        profile_params.update({
            "binding_sites": "assets/binding_sites.csv",
            "target_drug_map": "assets/target_drug_map.csv",
            "box_center_mode": "binding_site",
            "site_on_missing": "fail",
        })
    elif pipeline_id == "romero-v2":
        profile_params.update({
            "romero_maf": "tests/reference/romero_v2/raw/41467_2021_22478_MOESM8_ESM.xlsx",
            "romero_drivers": "tests/reference/romero_v2/raw/41467_2021_22478_MOESM9_ESM.xlsx",
            "romero_clinical": "tests/reference/romero_v2/raw/41467_2021_22478_MOESM4_ESM.xlsx",
            "fasta_dir": "tests/reference/romero_v2/fasta",
            "structures_dir": "tests/reference/romero_v2/structures",
        })
    elif pipeline_id == "romero-v2_1":
        profile_params.update({
            "romero_maf": "tests/reference/romero_v2/raw/41467_2021_22478_MOESM8_ESM.xlsx",
            "romero_drivers": "tests/reference/romero_v2/raw/41467_2021_22478_MOESM9_ESM.xlsx",
            "romero_clinical": "tests/reference/romero_v2/raw/41467_2021_22478_MOESM4_ESM.xlsx",
            "fasta_dir": "tests/reference/romero_v2/fasta",
            "structures_dir": "tests/reference/romero_v2/structures",
        })
    elif pipeline_id == "tcga-v3":
        profile_params.update({
            "cohort_ethnicity": "HISPANIC OR LATINO",
            "clinical_ingest": True,
            "clinical_attributes": "RACE,ETHNICITY,AGE",
            "clinical_small_cell": 5,
            "total_samples": 39,
            "contract_dir": "tests/reference/tcga_hispanic_v3",
            "contract_manifest": "tests/reference/tcga_hispanic_v3/manifest.json",
            "structures_dir": "tests/reference/structures",
        })
    effective_params = {**profile_params, **params}
    count = variant_count(pipeline_id, selected_genes, maximum_variants)
    wild_types = analyzed_gene_count(pipeline_id, selected_genes)
    receptors = count + wild_types
    drugs = drug_count(pipeline_id, selected_genes)
    pairs = receptors * drugs
    history = historical_vina_durations()
    timeout_bound = math.ceil(pairs * (timeout + 300) / parallel)
    if len(history) >= 5:
        median = statistics.median(history)
        sorted_history = sorted(history)
        p90 = sorted_history[min(len(sorted_history) - 1, math.ceil(len(sorted_history) * 0.9) - 1)]
        docking_low = math.ceil(pairs * median / parallel)
        docking_high = max(math.ceil(pairs * max(p90, median) / parallel), timeout_bound)
        estimate = {
            "kind": "historical",
            "samples": len(history),
            "docking_seconds_estimate": docking_low,
            "docking_seconds_low": docking_low,
            "docking_seconds_high": docking_high,
            "total_seconds_estimate": docking_low + 1200,
            "total_seconds_low": docking_low + 1200,
            "total_seconds_high": docking_high + 2700,
            "timeout_bound_seconds": timeout_bound,
            "note": "El tiempo esperado usa dockings historicos completados; el limite superior supone que cada par alcanza timeout. Incluye 20-45 min para etapas no-Vina.",
        }
    else:
        docking_bound = timeout_bound
        estimate = {
            "kind": "timeout-bound",
            "samples": len(history),
            "docking_seconds_low": None,
            "docking_seconds_high": docking_bound,
            "timeout_bound_seconds": docking_bound,
            "total_seconds_low": None,
            "total_seconds_high": docking_bound + 2700,
            "note": "Sin suficiente historico; muestra el limite de timeout agregado con el paralelismo actual.",
        }
    estimate["warnings"] = (
        ["La cota conservadora supera seis horas; reduce variantes, genes, modos o exhaustividad."]
        if estimate["total_seconds_high"] > 6 * 3600 else []
    )
    return params, {
        "pipeline": pipeline_id,
        "pipeline_label": pipeline["label"],
        "workflow": pipeline["workflow"],
        "profile": pipeline["profile"],
        "experiment": pipeline["experiment"],
        "effective_config": {
            "workflow_file": pipeline["workflow"],
            "profile": pipeline["profile"],
            "params": effective_params,
            "run_options": {"resume": bool(payload.get("resume", True))},
            "processes": {
                "RUN_VINA": {
                    "cpus": 1,
                    "memory": "3 GB",
                    "max_forks": parallel,
                    "nextflow_timeout_seconds": timeout + 300,
                    "vina_timeout_seconds": timeout,
                },
                "PREDICT_STRUCTURE": {"cpus": 2, "memory": "4 GB", "max_forks": 2},
            },
        },
        "variant_count_estimate": count,
        "wild_type_receptors_estimate": wild_types,
        "receptor_count_estimate": receptors,
        "drug_count_estimate": drugs,
        "docking_pairs_estimate": pairs,
        "params": params,
        "estimate": estimate,
        "resume": bool(payload.get("resume", True)),
    }


def read_status() -> dict:
    return load_json(STATUS_PATH, {"status": "idle", "run_name": None})


def process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def project_nextflow_active() -> bool:
    root = str(ROOT).encode("utf-8")
    for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            command = cmdline.read_bytes()
        except OSError:
            continue
        if root in command and b"nextflow" in command and b"run" in command:
            return True
    return False


def tail_file(path: Path, max_bytes: int = 160_000) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def write_status(data: dict) -> None:
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    temp = STATUS_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(STATUS_PATH)


def manager_call(action: str, run_name: str, experiment: str,
                 config_path: Path, workflow: str, manifest_path: Path | None = None,
                 status: str | None = None, exit_code: int = 0) -> str:
    command = [
        "docker", "run", "--rm", "--network", DOCKER_NETWORK,
        "-v", f"{ROOT}:/workspace:ro", "-w", "/workspace", MLFLOW_IMAGE,
        "python3", "/workspace/bin/manage_mlflow_run.py", action,
        "--tracking-uri", MLFLOW_URI, "--experiment", experiment,
        "--run-name", run_name,
        "--workflow-file", workflow,
        "--params-json", f"/workspace/{config_path.relative_to(ROOT).as_posix()}",
    ]
    if manifest_path:
        command.extend(("--manifest", f"/workspace/{manifest_path.relative_to(ROOT).as_posix()}"))
    if action == "finish":
        command.extend(("--status", status or "failed", "--exit-code", str(exit_code)))
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or "MLflow no pudo registrar el run")
    return result.stdout.strip()


def build_command(run_name: str, pipeline: dict, params_path: Path, trace_path: Path,
                  resume: bool) -> list[str]:
    workflow_path = ROOT / pipeline["workflow"]
    if not workflow_path.is_file():
        raise RuntimeError(f"No existe el workflow {workflow_path.name}.")
    command = [
        "nextflow", "run", str(workflow_path),
        "-profile", pipeline["profile"],
        "-name", run_name,
        "-params-file", str(params_path),
        "-with-trace", str(trace_path),
    ]
    if resume:
        command.append("-resume")
    return command


def run_watcher(process: subprocess.Popen, status: dict, log_handle) -> None:
    global CURRENT_PROCESS
    exit_code = process.wait()
    log_handle.flush()
    log_handle.close()
    status["status"] = "completed" if exit_code == 0 else "failed"
    status["exit_code"] = exit_code
    status["updated_at"] = utc_now()
    write_status(status)
    try:
        manager_call("finish", status["run_name"], status["mlflow_experiment"],
                     ROOT / status["config_file"], status["workflow"],
                     status=status["status"], exit_code=exit_code)
    except Exception as exc:  # noqa: BLE001
        status["mlflow_finalize_error"] = str(exc)
        status["updated_at"] = utc_now()
        write_status(status)
    with START_LOCK:
        CURRENT_PROCESS = None


class Handler(BaseHTTPRequestHandler):
    server_version = "GEMAMX-Pipeline-Control/1.0"

    def send_json(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        origin = self.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin")
        if origin not in ALLOWED_ORIGINS:
            self.send_error(403)
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/api/v1/options":
            payload = {key: {"label": value["label"], "workflow": value["workflow"], "profile": value["profile"], "experiment": value["experiment"], "genes": value["genes"], "max_variants_limit": value["max_variants_limit"], "defaults": value["defaults"]} for key, value in PIPELINES.items()}
            self.send_json(200, {"pipelines": payload})
            return
        if route == "/api/v1/status":
            status = read_status()
            config_path = ROOT / status.get("config_file", "") if status.get("config_file") else None
            log_path = ROOT / status.get("log_file", "") if status.get("log_file") else None
            trace_path = ROOT / status.get("trace_file_path", "") if status.get("trace_file_path") else None
            status["config"] = load_json(config_path, {}) if config_path else {}
            status["log_tail"] = tail_file(log_path) if log_path else ""
            status["trace_tail"] = tail_file(trace_path, max_bytes=80_000) if trace_path else ""
            self.send_json(200, status)
            return
        self.send_json(404, {"error": "Ruta no encontrada"})

    def do_POST(self) -> None:
        origin = self.headers.get("Origin")
        if origin and origin not in ALLOWED_ORIGINS:
            self.send_json(403, {"error": "Origen no permitido"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 32_000:
                raise ValueError("Solicitud vacia o demasiado grande.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("El cuerpo debe ser un objeto JSON.")
            route = urlparse(self.path).path
            if route == "/api/v1/estimate":
                _, summary = validate_config(payload)
                self.send_json(200, summary)
                return
            if route == "/api/v1/start":
                self.start_pipeline(payload)
                return
            self.send_json(404, {"error": "Ruta no encontrada"})
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except RuntimeError as exc:
            self.send_json(503, {"error": str(exc)})

    def start_pipeline(self, payload: dict) -> None:
        global CURRENT_PROCESS
        with START_LOCK:
            if CURRENT_PROCESS is not None and CURRENT_PROCESS.poll() is None:
                self.send_json(409, {"error": "Ya hay una ejecucion de Nextflow activa."})
                return
            current = read_status()
            if current.get("status") == "running":
                if process_alive(current.get("runner_pid")) or project_nextflow_active():
                    self.send_json(409, {"error": "El monitor registra una ejecucion activa."})
                    return
                current["status"] = "failed"
                current["exit_code"] = 1
                current["updated_at"] = utc_now()
                write_status(current)
            elif project_nextflow_active():
                self.send_json(409, {"error": "Hay un Nextflow activo para este proyecto."})
                return

            params, summary = validate_config(payload)
            pipeline = PIPELINES[summary["pipeline"]]
            run_name = f"web_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            LIVE_DIR.mkdir(parents=True, exist_ok=True)
            config_path = LIVE_DIR / f"{run_name}.config.json"
            trace_path = LIVE_DIR / f"{run_name}.trace.tsv"
            log_path = LIVE_DIR / f"{run_name}.log"
            params_path = LIVE_DIR / f"{run_name}.params.json"
            params_path.write_text(json.dumps(params, indent=2) + "\n", encoding="utf-8")
            config = {
                **summary,
                "run_name": run_name,
                "created_at": utc_now(),
                "nextflow_params": params,
            }
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            trace_path.write_text("", encoding="utf-8")
            log_handle = log_path.open("a", encoding="utf-8", buffering=1)
            log_handle.write(f"GEMA MX local runner\nRun: {run_name}\nProfile: {pipeline['profile']}\nConfig: {config_path.name}\n\n")
            command = build_command(run_name, pipeline, params_path, trace_path, config["resume"])
            status = {
                "run_name": run_name,
                "pipeline": summary["pipeline"],
                "pipeline_label": pipeline["label"],
                "workflow": pipeline["workflow"],
                "profile": pipeline["profile"],
                "status": "starting",
                "started_at": utc_now(),
                "updated_at": utc_now(),
                "exit_code": None,
                "trace_file": trace_path.name,
                "trace_file_path": trace_path.relative_to(ROOT).as_posix(),
                "log_file": log_path.relative_to(ROOT).as_posix(),
                "config_file": config_path.relative_to(ROOT).as_posix(),
                "mlflow_experiment": pipeline["experiment"],
                "estimated_seconds_low": config["estimate"]["total_seconds_low"],
                "estimated_seconds_high": config["estimate"]["total_seconds_high"],
            }
            write_status(status)

            try:
                manifest_path = ROOT / "tests/reference/tcga_hispanic_v3/manifest.json" if summary["pipeline"] == "tcga-v3" else None
                manager_output = manager_call("start", run_name, pipeline["experiment"],
                                               config_path, pipeline["workflow"],
                                               manifest_path=manifest_path)
                id_line = next((line for line in reversed(manager_output.splitlines()) if "\t" in line), "")
                ids = id_line.split("\t")
                if len(ids) != 2 or not all(ids):
                    raise RuntimeError(f"Respuesta inesperada del registro MLflow: {manager_output[-300:]}")
                experiment_id, mlflow_run_id = ids[0], ids[1]
            except Exception as exc:  # noqa: BLE001
                status["status"] = "failed"
                status["exit_code"] = 1
                status["updated_at"] = utc_now()
                status["error"] = f"No se pudo registrar la configuracion en MLflow: {exc}"
                log_handle.write(f"ERROR: {status['error']}\n")
                log_handle.close()
                write_status(status)
                try:
                    manager_call("finish", run_name, pipeline["experiment"],
                                 config_path, pipeline["workflow"], status="failed", exit_code=1)
                except Exception as finalize_error:  # noqa: BLE001
                    status["mlflow_finalize_error"] = str(finalize_error)
                    write_status(status)
                self.send_json(503, {"error": f"No se pudo registrar la configuracion en MLflow: {exc}"})
                return

            log_handle.write("Comando: " + " ".join(command) + "\n\n")
            status["mlflow_run_id"] = mlflow_run_id
            status["mlflow_experiment_id"] = experiment_id
            write_status(status)
            env = dict(os.environ)
            env["NXF_ANSI_LOG"] = "false"
            try:
                CURRENT_PROCESS = subprocess.Popen(
                    command, cwd=ROOT, env=env, stdout=log_handle,
                    stderr=subprocess.STDOUT, start_new_session=True,
                )
            except OSError as exc:
                log_handle.close()
                status["status"] = "failed"
                status["exit_code"] = 127
                status["updated_at"] = utc_now()
                status["error"] = str(exc)
                write_status(status)
                try:
                    manager_call("finish", run_name, pipeline["experiment"],
                                 config_path, pipeline["workflow"], status="failed", exit_code=127)
                except Exception:
                    pass
                self.send_json(503, {"error": f"No se pudo iniciar Nextflow: {exc}"})
                return
            status["status"] = "running"
            status["runner_pid"] = CURRENT_PROCESS.pid
            write_status(status)
            threading.Thread(target=run_watcher, args=(CURRENT_PROCESS, status, log_handle), daemon=True).start()
            self.send_json(202, {"status": "running", "run_name": run_name, "mlflow_run_id": mlflow_run_id, "estimate": config["estimate"]})

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.log_date_time_string()} {self.address_string()} {fmt % args}", flush=True)


def main() -> None:
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Pipeline control API listening on http://127.0.0.1:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
