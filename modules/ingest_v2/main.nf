/*
 * INGEST_V2 — lee los archivos pre-computados del pipeline V2 (Romero-Córdoba)
 * y los ensambla en el contrato de datos que consumen PUBLISH y LOG_MLFLOW.
 *
 * Sustituye la cadena INGEST→FETCH_FASTA→PREDICT_STRUCTURE→ALIGN→DOCKING del
 * pipeline V1: todos esos pasos ya fueron ejecutados offline (Boltz-1 en Colab
 * + Vina local) y sus resultados viven en tests/reference/romero_v2/.
 *
 * M5 (clinical summary) también es pre-computado para V2 y se publica aquí.
 */

process INGEST_V2 {
    tag "${params.study_id}"
    container "${params.image_cpu}"

    publishDir "${params.outdir}", mode: 'copy', overwrite: true,
               enabled: !workflow.stubRun, saveAs: { fn ->
        fn.startsWith("stage/") ? fn.substring("stage/".length()) : fn
    }

    input:
    path top_variants
    path raw_mutations
    path mutation_stats
    path structural_metrics
    path vina_affinities
    path manifest_structures
    path clinical_summary
    path struct_dir,  stageAs: "structures_src"
    path drug_catalog

    output:
    path "stage/data/top_variants.json",                    emit: top_variants_out
    path "stage/data/raw_mutations.json",                   emit: raw_mutations_out
    path "stage/data/mutation_stats.json",                  emit: mutation_stats_out
    path "stage/data/structural_metrics.json",              emit: structural_metrics_out
    path "stage/data/manifest_structures.json",             emit: manifest_structures_out
    path "stage/data/docking/vina_affinities.json",         emit: vina_affinities_out
    path "stage/data/variant_clinical_summary.json",        optional: true, emit: clinical_summary_out
    path "stage/data/structures/*",                         optional: true, emit: structures_out

    script:
    def clinical_arg = (clinical_summary && clinical_summary.toString() != 'null')
        ? "--clinical \"${clinical_summary}\"" : ""
    def catalog_arg  = (drug_catalog && drug_catalog.toString() != 'null')
        ? "--catalog \"${drug_catalog}\"" : ""
    """
    mkdir -p stage/data

    ingest_v2.py \\
        --top             "${top_variants}" \\
        --raw             "${raw_mutations}" \\
        --stats           "${mutation_stats}" \\
        --structural      "${structural_metrics}" \\
        --vina            "${vina_affinities}" \\
        --manifest        "${manifest_structures}" \\
        --struct-dir      structures_src \\
        ${clinical_arg} \\
        ${catalog_arg} \\
        --outdir          stage/data
    """

    stub:
    """
    mkdir -p stage/data/docking
    cp "${top_variants}"       stage/data/top_variants.json
    cp "${raw_mutations}"      stage/data/raw_mutations.json
    cp "${mutation_stats}"     stage/data/mutation_stats.json
    cp "${structural_metrics}" stage/data/structural_metrics.json
    cp "${manifest_structures}" stage/data/manifest_structures.json
    cp "${vina_affinities}"    stage/data/docking/vina_affinities.json
    """
}
