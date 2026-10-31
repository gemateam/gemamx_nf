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
    // Emitir el directorio completo con su estructura interna preservada.
    path "stage/data", emit: contract_data

    script:
    """
    mkdir -p stage/data

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
    mkdir -p stage/data/docking/results stage/data/docking/complex stage/data/structures
    echo '[]'  > stage/data/top_variants.json
    echo '[]'  > stage/data/raw_mutations.json
    echo '{}'  > stage/data/mutation_stats.json
    echo '{}'  > stage/data/structural_metrics.json
    echo '{}'  > stage/data/manifest_structures.json
    echo '[]'  > stage/data/docking/vina_affinities.json
    echo 'PDB' > stage/data/structures/PIK3CA_WT.pdb
    echo 'PDB' > stage/data/structures/PIK3CA_H1047R.pdb
    """
}

process PUBLISH {
    tag "${run_name}"
    // Sin contenedor: corre en el host directamente para poder escribir al outdir.
    // Python3 debe estar disponible en el host; si no, se puede instalar con:
    //   apt install python3  (Ubuntu/WSL2)
    container null

    // publishDir copia data/ y run_manifest.json al outdir del host.
    publishDir "${params.outdir}", mode: 'copy', overwrite: true

    input:
    path contract_data
    val  run_name
    val  commit_hash

    output:
    path "run_manifest.json", emit: run_manifest
    path "params.json",       emit: run_params
    path "data/**",           emit: data_files

    script:
    def params_json = groovy.json.JsonOutput.prettyPrint(
        groovy.json.JsonOutput.toJson(params)
    )
    """
    cat << 'PARAMS_EOF' > params.json
${params_json}
PARAMS_EOF

    cat << IMAGES_EOF > images.json
{
  "image_cpu": "${params.image_cpu}",
  "image_docking": "${params.image_docking}",
  "image_gpu": "${params.image_gpu}",
  "image_mlflow": "${params.image_mlflow}"
}
IMAGES_EOF

    publish_results.py \\
        --source "${contract_data}" \\
        --outdir  . \\
        --run-name "${run_name}" \\
        --commit "${commit_hash}" \\
        --params "params.json" \\
        --images "images.json"
    """

    stub:
    """
    mkdir -p data
    echo '{"run_name":"${run_name}","commit":"${commit_hash}","files":{}}' > run_manifest.json
    echo '{}' > params.json
    touch data/top_variants.json
    """
}
