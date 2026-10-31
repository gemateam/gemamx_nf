#!/usr/bin/env python3
"""upload_nf_reports — sube los reportes HTML de Nextflow a un run de MLflow.

Se ejecuta desde el host (fuera de Docker) justo después de que el pipeline
finaliza, cuando Nextflow ya ha generado los archivos HTML.

Uso:
    python bin/upload_nf_reports.py \\
        --tracking-uri http://localhost:5000 \\
        --experiment   GEMAMX-V1-NF \\
        --run-name     friendly_swanson \\
        --pipeline-info results/pipeline_info

Los reportes se publican en el run padre bajo el subdirectorio
`nextflow_reports/` y son consultables directamente en la pestaña
Artifacts de la UI de MLflow.

Idempotencia: si un artefacto ya existe en el run no se duplica (MLflow
sobreescribe el archivo con el mismo contenido).

Salida (stdout):
    OK: <n> reporte(s) subidos a run <run_id> -> <tracking_uri>
    SKIP: sin reportes en <pipeline_info_dir>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Los nombres que genera Nextflow con los flags -with-report / -with-timeline / -with-dag
NF_REPORT_FILES = ["report.html", "timeline.html", "dag.html"]


def die(message: str, code: int = 1) -> "NoReturn":
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def find_run(client, experiment_id: str, run_name: str):
    """Localiza el run padre por gemamx.run_name."""
    found = client.search_runs(
        experiment_ids=[experiment_id],
        filter_string=f"tags.\"gemamx.run_name\" = '{run_name}'",
        max_results=10,
        order_by=["attributes.start_time DESC"],
    )
    # El run padre no tiene gemamx.stage
    for run in found:
        if not run.data.tags.get("gemamx.stage"):
            return run
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sube reportes HTML de Nextflow al run padre en MLflow"
    )
    parser.add_argument(
        "--tracking-uri", required=True,
        help="URI del servidor MLflow (ej. http://localhost:5000)",
    )
    parser.add_argument(
        "--experiment", default="GEMAMX-V1-NF",
        help="Nombre del experimento en MLflow",
    )
    parser.add_argument(
        "--run-name", required=True,
        help="workflow.runName que identifica la corrida (ej. friendly_swanson)",
    )
    parser.add_argument(
        "--pipeline-info",
        help=(
            "Directorio con los reportes HTML de Nextflow "
            "(por defecto: <outdir>/pipeline_info, se usa results/pipeline_info)"
        ),
        default="results/pipeline_info",
    )
    parser.add_argument(
        "--extra", action="append", default=[],
        metavar="PATH",
        help="Archivo adicional a subir (repetible)",
    )
    args = parser.parse_args()

    try:
        import mlflow
        from mlflow import MlflowClient
    except ImportError:
        die("MLflow no instalado. Ejecuta: pip install mlflow")

    mlflow.set_tracking_uri(args.tracking_uri)
    client = MlflowClient(tracking_uri=args.tracking_uri)

    # Resolver experimento
    experiment = client.get_experiment_by_name(args.experiment)
    if experiment is None:
        die(f"experimento no encontrado: {args.experiment!r}")
    experiment_id = experiment.experiment_id

    # Localizar run padre
    run = find_run(client, experiment_id, args.run_name)
    if run is None:
        die(
            f"run no encontrado: run_name={args.run_name!r} en experimento "
            f"{args.experiment!r}. Verifica que el pipeline haya completado y "
            "que LOG_MLFLOW haya registrado la corrida."
        )
    run_id = run.info.run_id

    # Recopilar archivos a subir
    info_dir = Path(args.pipeline_info)
    files_to_upload: list[Path] = []

    for name in NF_REPORT_FILES:
        candidate = info_dir / name
        if candidate.is_file():
            files_to_upload.append(candidate)

    for extra in args.extra:
        p = Path(extra)
        if p.is_file():
            files_to_upload.append(p)
        else:
            print(f"WARN: archivo extra no encontrado, se ignora: {extra}", file=sys.stderr)

    if not files_to_upload:
        print(f"SKIP: sin reportes en {info_dir} (el pipeline puede no haber generado aún los HTMLs)")
        return 0

    # Subir bajo nextflow_reports/ en el run padre
    with mlflow.start_run(run_id=run_id):
        for path in files_to_upload:
            mlflow.log_artifact(str(path), artifact_path="nextflow_reports")
            print(f"  ✓ {path.name}")

    print(
        f"OK: {len(files_to_upload)} reporte(s) subidos al run {run_id} "
        f"(nextflow_reports/) -> {args.tracking_uri}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
