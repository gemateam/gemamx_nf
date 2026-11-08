/*
 * Módulos del pipeline V2 — etapas M1/M2 (ingestión Romero) y M5 (clínico).
 */

// ─── M1 / M2 — Ingestión y priorización Romero ────────────────────────────────
// Parsea MOESM8 (MAF) + MOESM9 (drivers) directamente desde los XLSX del
// artículo de Romero-Córdoba 2021. No consulta cBioPortal.
process INGEST_ROMERO {
    tag "romero_hm"
    container "${params.image_cpu}"

    input:
    path maf_xlsx            // 41467_2021_22478_MOESM8_ESM.xlsx
    path drivers_xlsx        // 41467_2021_22478_MOESM9_ESM.xlsx
    path clinical_xlsx       // 41467_2021_22478_MOESM4_ESM.xlsx (hash de procedencia)

    output:
    path "raw_mutations.json",   emit: raw_mutations
    path "top_variants.json",    emit: top_variants
    path "mutation_stats.json",  emit: mutation_stats
    path "data_ingest.json",     emit: ingest_metadata

    script:
    """
    ingest_romero.py \\
        --maf     "${maf_xlsx}" \\
        --drivers "${drivers_xlsx}" \\
        --clinical "${clinical_xlsx}" \\
        --genes   "${params.genes}" \\
        --max-variants ${params.max_variants} \\
        --outdir  .
    """

    stub:
    """
    echo '[{"hugo_symbol":"PIK3CA","protein_change":"H1047R","frequency":15,"cohort_percentage":11.19,"chromosome":"3","start_position":178952085,"classification":"Patogénica","rank":1,"dataset":"Romero-Cordoba 2021 HM"}]' > top_variants.json
    echo '[]' > raw_mutations.json
    echo '{"total_samples":134,"total_mutations":28114,"dataset":"Romero-Cordoba 2021 HM"}' > mutation_stats.json
    echo '{"schema_version":1,"mode":"stub","query":{},"counts":{}}' > data_ingest.json
    """
}

// ─── M5a — Extracción de metadatos clínicos ───────────────────────────────────
// Parsea MOESM4 (Features): edad, subtipo IHC, PAM50, grado SBR, histología.
process EXTRACT_CLINICAL {
    tag "clinical_romero"
    container "${params.image_cpu}"

    input:
    path clinical_xlsx       // 41467_2021_22478_MOESM4_ESM.xlsx

    output:
    path "clinical_metadata.json", emit: clinical_metadata

    script:
    """
    extract_clinical_romero.py \\
        --source  "${clinical_xlsx}" \\
        --outdir  .
    """

    stub:
    """
    echo '[{"sample_id":"SAMPLE1","age":55,"ihc_subtype":"Luminal A","pam50":"LumA"}]' > clinical_metadata.json
    """
}

// ─── M5b — Resumen clínico por variante ──────────────────────────────────────
// Cruza raw_mutations + clinical_metadata + top_variants para producir
// perfiles clínicos (edad media, distribución IHC, PAM50, grado SBR).
process BUILD_CLINICAL_SUMMARY {
    tag "clinical_summary"
    container "${params.image_cpu}"

    input:
    path raw_mutations
    path clinical_metadata
    path top_variants

    output:
    path "variant_clinical_summary.json", emit: clinical_summary

    script:
    """
    build_clinical_summary.py \\
        --raw      "${raw_mutations}" \\
        --clinical "${clinical_metadata}" \\
        --top      "${top_variants}" \\
        --outdir   .
    """

    stub:
    """
    echo '[{"variant_id":"PIK3CA_H1047R","sample_count":15,"highlights":{}}]' > variant_clinical_summary.json
    """
}
