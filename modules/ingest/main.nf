process INGEST {
    tag "${params.study_id}"
    container "${params.image_cpu}"

    input:
    // Cuando no hay snapshot, se recibe una lista vacía [] (Channel.value([])).
    // Nextflow interpreta [] como "sin archivo" y no crea un path en el directorio
    // de trabajo; el script lo detecta con la variable de entorno vacía.
    path mutations_json
    path clinical_json
    // Bundle del Contrato V3 y su informe de validación (vacío en V1/V2).
    path contract_dir
    path contract_validation

    output:
    path "top_variants.json",   emit: top_variants
    path "raw_mutations.json",  emit: raw_mutations
    path "mutation_stats.json", emit: mutation_stats
    path "data_ingest.json",    emit: ingest_metadata
    // Solo se generan con clinical_ingest / clinical_json (RACE, ETHNICITY, AGE).
    path "clinical_metadata.json",        optional: true, emit: clinical_metadata
    path "variant_clinical_summary.json", optional: true, emit: clinical_summary
    // Solo en modo contrato V3: procedencia para webapp y MLflow.
    path "contract_provenance.json",      optional: true, emit: provenance

    script:
    def snapshot_arg = (mutations_json && mutations_json != [] && mutations_json.toString() != 'null') \
        ? "--mutations-json ${mutations_json}" : ""
    def has_contract = (contract_dir && contract_dir != [] \
        && contract_dir.toString() != 'null' && contract_dir.toString() != '[]')
    def contract_arg = has_contract ? "--contract-dir ${contract_dir}" : ""
    def allow_curated_arg = (params.containsKey('contract_allow_curated') \
        && params.contract_allow_curated) ? "--allow-curated" : ""
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
        ${contract_arg} \\
        ${allow_curated_arg} \\
        ${total_samples_arg} \\
        ${clinical_arg} \\
        ${clinical_snapshot_arg} \\
        ${clinical_opts_arg} \\
        --outdir .

    build_stats.py \\
        --raw raw_mutations.json \\
        --out mutation_stats.json \\
        ${contract_arg} \\
        ${total_samples_arg}
    """

    stub:
    """
    echo '[{"hugo_symbol":"PIK3CA","protein_change":"H1047R","frequency":454,"cohort_percentage":32.5,"chromosome":"3","start_position":179234297,"classification":"Patogénica"}]' > top_variants.json
    echo '[]' > raw_mutations.json
    echo '{"total_samples":1397,"total_mutations":2458}' > mutation_stats.json
    echo '{"schema_version":1,"mode":"stub","query":{},"counts":{}}' > data_ingest.json
    if [ "${params.clinical_ingest}" = "true" ]; then
        echo '[]' > clinical_metadata.json
        echo '[]' > variant_clinical_summary.json
    fi
    """
}
