process INGEST {
    tag "${params.study_id}"
    container "${params.image_cpu}"

    input:
    // Cuando no hay snapshot, se recibe una lista vacía [] (Channel.value([])).
    // Nextflow interpreta [] como "sin archivo" y no crea un path en el directorio
    // de trabajo; el script lo detecta con la variable de entorno vacía.
    path mutations_json

    output:
    path "top_variants.json",   emit: top_variants
    path "raw_mutations.json",  emit: raw_mutations
    path "mutation_stats.json", emit: mutation_stats

    script:
    def snapshot_arg = (mutations_json && mutations_json != [] && mutations_json.toString() != 'null') \
        ? "--mutations-json ${mutations_json}" : ""
    """
    ingest_cbioportal.py \\
        --study "${params.study_id}" \\
        --genes "${params.genes}" \\
        --max-variants ${params.max_variants} \\
        ${snapshot_arg} \\
        --outdir .

    build_stats.py \\
        --raw raw_mutations.json \\
        --out mutation_stats.json
    """

    stub:
    """
    echo '[{"hugo_symbol":"PIK3CA","protein_change":"H1047R","frequency":454,"cohort_percentage":32.5,"chromosome":"3","start_position":179234297,"classification":"Patogénica"}]' > top_variants.json
    echo '[]' > raw_mutations.json
    echo '{"total_samples":1397,"total_mutations":2458}' > mutation_stats.json
    """
}
