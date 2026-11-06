process INGEST {
    tag "${params.study_id}"
    container "${params.image_cpu}"

    input:
    // Cuando no hay snapshot, se recibe una lista vacía [] (Channel.value([])).
    // Nextflow interpreta [] como "sin archivo" y no crea un path en el directorio
    // de trabajo; el script lo detecta con la variable de entorno vacía.
    path mutations_json
    path clinical_json

    output:
    path "top_variants.json",   emit: top_variants
    path "raw_mutations.json",  emit: raw_mutations
    path "mutation_stats.json", emit: mutation_stats
    // Solo se generan con clinical_ingest / clinical_json (RACE, ETHNICITY, AGE).
    path "clinical_metadata.json",        optional: true, emit: clinical_metadata
    path "variant_clinical_summary.json", optional: true, emit: clinical_summary

    script:
    def snapshot_arg = (mutations_json && mutations_json != [] && mutations_json.toString() != 'null') \
        ? "--mutations-json ${mutations_json}" : ""
    def total_samples_arg = params.containsKey('total_samples') && params.total_samples \
        ? "--total-samples ${params.total_samples}" : ""
    def has_clinical_snapshot = (clinical_json && clinical_json != [] \
        && clinical_json.toString() != 'null')
    def clinical_arg = (params.clinical_ingest || has_clinical_snapshot) ? "--clinical" : ""
    def clinical_snapshot_arg = has_clinical_snapshot \
        ? "--clinical-json ${clinical_json}" : ""
    def clinical_opts_arg = (params.clinical_ingest || has_clinical_snapshot) \
        ? "--clinical-attributes '${params.clinical_attributes}' --clinical-small-cell ${params.clinical_small_cell}" : ""
    """
    ingest_cbioportal.py \\
        --study "${params.study_id}" \\
        --genes "${params.genes}" \\
        --max-variants ${params.max_variants} \\
        ${snapshot_arg} \\
        ${total_samples_arg} \\
        ${clinical_arg} \\
        ${clinical_snapshot_arg} \\
        ${clinical_opts_arg} \\
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
    if [ "${params.clinical_ingest}" = "true" ]; then
        echo '[]' > clinical_metadata.json
        echo '[]' > variant_clinical_summary.json
    fi
    """
}
