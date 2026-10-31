process LOG_MLFLOW {
    tag "${run_name}"
    container "${params.image_mlflow}"

    input:
    val  run_name
    val  tracking_uri
    val  experiment_name
    val  commit_hash
    path run_manifest
    path run_params
    path data_files, stageAs: "data/*"

    output:
    path "mlflow_runs.json", emit: mlflow_ids

    script:
    """
    log_mlflow.py \\
        --tracking-uri "${tracking_uri}" \\
        --experiment "${experiment_name}" \\
        --run-name "${run_name}" \\
        --params "${run_params}" \\
        --run-manifest "${run_manifest}" \\
        --data-dir data \\
        --structural-metrics data/structural_metrics.json \\
        --vina-affinities data/docking/vina_affinities.json \\
        --git-commit "${commit_hash}" \\
        --out "mlflow_runs.json"
    """

    stub:
    """
    echo '{"parent_run_id":"stub","child_runs":{}}' > mlflow_runs.json
    """
}
