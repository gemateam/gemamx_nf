process BUILD_JSONS {
    tag "contract_jsons"
    container "${params.image_cpu}"

    input:
    path top_variants
    path raw_mutations
    path mutation_stats
    path drug_catalog
    path struct_files,  stageAs: "structures/*"
    path rmsd_files,    stageAs: "rmsd/*"
    path vina_files,    stageAs: "vina/*"
    path complex_files, stageAs: "complex/*"

    output:
    path "stage/data", emit: contract_data

    script:
    """
    mkdir -p stage/data

    # Copiar poses PDBQT referenciadas por los resúmenes de Vina al directorio de ejecución
    # para que build_jsons.py pueda resolverlas junto al summary.json
    find vina -type l -o -type f -name "*_out.pdbqt" -exec cp {} vina/ \\; 2>/dev/null || true

    build_jsons.py \\
        --top "${top_variants}" \\
        --raw "${raw_mutations}" \\
        --stats "${mutation_stats}" \\
        --catalog "${drug_catalog}" \\
        \$(ls structures/*.json 2>/dev/null | sed 's/^/--structure-meta /' | tr '\\n' ' ') \\
        \$(ls rmsd/*.json 2>/dev/null | sed 's/^/--rmsd /' | tr '\\n' ' ') \\
        \$(ls vina/*_summary.json 2>/dev/null | sed 's/^/--vina /' | tr '\\n' ' ') \\
        \$(ls complex/*.pdb 2>/dev/null | sed 's/^/--complex /' | tr '\\n' ' ') \\
        --outdir stage/data
    """

    stub:
    """
    mkdir -p stage/data/docking/results stage/data/docking/complex stage/data/structures stage/data/raw_pages
    echo '[]' > stage/data/top_variants.json
    echo '[]' > stage/data/raw_mutations.json
    echo '{}' > stage/data/mutation_stats.json
    echo '{}' > stage/data/structural_metrics.json
    echo '{}' > stage/data/manifest_structures.json
    echo '[]' > stage/data/docking/vina_affinities.json
    echo '{"pages":[]}' > stage/data/raw_pages/index.json
    """
}

process PUBLISH {
    tag "${run_name}"
    container "${params.image_cpu}"

    input:
    path contract_data
    val run_name
    val outdir_path
    val commit_hash

    output:
    path "run_manifest.json", emit: run_manifest
    path "params.json",       emit: run_params

    script:
    // Serializar params en Groovy (el bloque script corre en el contenedor y no
    // tiene acceso a clases Groovy del orquestador).
    def params_json = groovy.json.JsonOutput.prettyPrint(
        groovy.json.JsonOutput.toJson(params.properties
            .findAll { k, v -> !(k in ['class','metaClass']) && v != null }
        )
    )
    """
    cat << 'EOF' > params.json
${params_json}
EOF

    cat << EOF > images.json
{
  "image_cpu": "${params.image_cpu}",
  "image_docking": "${params.image_docking}",
  "image_gpu": "${params.image_gpu}",
  "image_mlflow": "${params.image_mlflow}"
}
EOF

    publish_results.py \\
        --source "${contract_data}" \\
        --target "${outdir_path}/data" \\
        --manifest "run_manifest.json" \\
        --params "params.json" \\
        --run-name "${run_name}" \\
        --commit "${commit_hash}" \\
        --images "images.json"
    """

    stub:
    """
    echo '{"run_name":"${run_name}","commit":"${commit_hash}","files":{}}' > run_manifest.json
    echo '{}' > params.json
    """
}

