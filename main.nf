nextflow.enable.dsl = 2

/*
 * ============================================================================
 * gemamx_nf — GEMA MX · Pipeline V1 (TCGA-BRCA)
 * Nextflow DSL2 · Docker · MLflow
 * ============================================================================
 */

include { INGEST }                                                         from './modules/ingest/main'
include { FETCH_FASTA_WT; FETCH_FASTA_MUT }                                from './modules/fasta/main'
include { PREDICT_STRUCTURE_WT; PREDICT_STRUCTURE_MUT; ALIGN_WT_MUT }     from './modules/structure/main'
include { PREP_LIGAND; PREP_RECEPTOR; DOCK_CENTER; RUN_VINA }              from './modules/docking/main'
include { BUILD_JSONS; PUBLISH }                                           from './modules/metrics/main'
include { LOG_MLFLOW }                                                     from './modules/mlflow/main'

workflow {

    // 1. Commit actual del repositorio para trazabilidad
    def commit_hash = 'unknown'
    try {
        def proc = ['git', 'rev-parse', 'HEAD'].execute()
        proc.waitFor()
        if (proc.exitValue() == 0) commit_hash = proc.text.trim()
    } catch (Exception e) { /* sin git disponible */ }

    // 2. Snapshot de mutaciones (opcional; Channel.empty() si no se pasa)
    def ch_mutations_input = params.mutations_json
        ? Channel.fromPath(params.mutations_json, checkIfExists: true)
        : Channel.value([])

    // 3. Catálogo de fármacos
    def drug_catalog_file = file(params.drug_catalog, checkIfExists: true)

    // ── INGEST ────────────────────────────────────────────────────────────────
    INGEST(ch_mutations_input)

    // Parsear variantes → [gene, protein_change]
    def ch_variants = INGEST.out.top_variants
        .flatMap { json_file ->
            def json = new groovy.json.JsonSlurper().parse(json_file)
            json.collect { row ->
                def gene = row.hugo_symbol ?: row.gene
                def pc   = row.protein_change
                tuple(gene, pc)
            }
        }

    // Genes únicos para WT (una sola descarga por gen)
    def ch_genes = ch_variants
        .map { gene, pc -> gene }
        .unique()

    // ── FASTA ─────────────────────────────────────────────────────────────────
    FETCH_FASTA_WT(ch_genes)

    // Combinar por gene: [gene, fasta_wt] × [gene, pc] → [gene, pc, fasta_wt]
    def ch_mut_with_wt = ch_variants
        .combine(FETCH_FASTA_WT.out.wt_fasta, by: 0)
        .map { gene, pc, fasta_wt -> tuple(gene, pc, fasta_wt) }

    FETCH_FASTA_MUT(ch_mut_with_wt)

    // ── ESTRUCTURAS 3D ────────────────────────────────────────────────────────
    def struct_dir = params.structures_dir ? file(params.structures_dir) : null

    def ch_wt_struct_input = FETCH_FASTA_WT.out.wt_fasta
        .map { gene, fasta ->
            def pdb  = struct_dir ? file("${struct_dir}/${gene}_WT.pdb")  : []
            def meta = struct_dir ? file("${struct_dir}/${gene}_WT.json") : []
            tuple(gene, fasta,
                  (pdb instanceof java.nio.file.Path && pdb.exists()) ? pdb  : [],
                  (meta instanceof java.nio.file.Path && meta.exists()) ? meta : [])
        }

    PREDICT_STRUCTURE_WT(ch_wt_struct_input)

    def ch_mut_struct_input = FETCH_FASTA_MUT.out.mut_fasta
        .map { gene, pc, fasta ->
            def pdb  = struct_dir ? file("${struct_dir}/${gene}_${pc}.pdb")  : []
            def meta = struct_dir ? file("${struct_dir}/${gene}_${pc}.json") : []
            tuple(gene, pc, fasta,
                  (pdb instanceof java.nio.file.Path && pdb.exists()) ? pdb  : [],
                  (meta instanceof java.nio.file.Path && meta.exists()) ? meta : [])
        }

    PREDICT_STRUCTURE_MUT(ch_mut_struct_input)

    // Alineamiento WT vs MUT: cross por gene
    // cross produce: [[gene, wt_pdb, wt_meta], [gene, pc, mut_pdb, mut_meta]]
    def ch_align_input = PREDICT_STRUCTURE_WT.out.wt_struct
        .cross(PREDICT_STRUCTURE_MUT.out.mut_struct)
        .map { wt, mut ->
            // wt  = [gene, wt_pdb, wt_meta]
            // mut = [gene, pc, mut_pdb, mut_meta]
            tuple(wt[0], mut[1], wt[1], wt[2], mut[2], mut[3])
        }

    ALIGN_WT_MUT(ch_align_input)

    // ── LIGANDOS Y RECEPTORES ─────────────────────────────────────────────────
    def ch_drugs = Channel.fromPath(drug_catalog_file)
        .splitCsv(header: true)
        .map { row -> tuple(row.name, drug_catalog_file) }

    PREP_LIGAND(ch_drugs)

    def ch_receptors = PREDICT_STRUCTURE_WT.out.wt_struct
        .map { gene, pdb, meta -> tuple("${gene}_WT", pdb, meta) }
        .mix(
            PREDICT_STRUCTURE_MUT.out.mut_struct
                .map { gene, pc, pdb, meta -> tuple("${gene}_${pc}", pdb, meta) }
        )

    PREP_RECEPTOR(ch_receptors)
    DOCK_CENTER(PREP_RECEPTOR.out.receptor_pdbqt)

    // Producto cartesiano Receptores × Ligandos
    def ch_docking_pairs = DOCK_CENTER.out.target_box
        .combine(PREP_LIGAND.out.ligand_pdbqt)
        // → [target_id, receptor_pdbqt, box_json, drug, ligand_pdbqt]

    // ── AUTODOCK VINA ─────────────────────────────────────────────────────────
    RUN_VINA(ch_docking_pairs)

    // ── BUILD JSONS ───────────────────────────────────────────────────────────
    // Recolectar todos los PDB+JSON de estructuras en una sola lista
    def ch_struct_files = PREDICT_STRUCTURE_WT.out.wt_struct
        .flatMap { gene, pdb, meta -> [pdb, meta] }
        .mix(
            PREDICT_STRUCTURE_MUT.out.mut_struct
                .flatMap { gene, pc, pdb, meta -> [pdb, meta] }
        )
        .collect()

    // Recolectar resúmenes Vina (summary + out.pdbqt) y complejos PDB
    def ch_vina_files = RUN_VINA.out.vina_summary
        .map { target, drug, summary -> summary }
        .mix(RUN_VINA.out.vina_out_pdbqt)
        .collect()

    def ch_complex_files = RUN_VINA.out.vina_complex_pdb.collect()

    BUILD_JSONS(
        INGEST.out.top_variants,
        INGEST.out.raw_mutations,
        INGEST.out.mutation_stats,
        drug_catalog_file,
        ch_struct_files,
        ALIGN_WT_MUT.out.rmsd_json.collect(),
        ch_vina_files,
        ch_complex_files
    )

    // ── PUBLISH ───────────────────────────────────────────────────────────────
    def abs_outdir = file(params.outdir).toAbsolutePath().toString()

    PUBLISH(
        BUILD_JSONS.out.contract_data,
        workflow.runName,
        abs_outdir,
        commit_hash
    )

    // ── LOG MLFLOW ────────────────────────────────────────────────────────────
    // Los reportes HTML (report, timeline, dag) los genera Nextflow al terminar;
    // bin/upload_nf_reports.py los sube vía run_pipeline.sh post-ejecución.
    LOG_MLFLOW(
        workflow.runName,
        params.mlflow_tracking_uri,
        params.mlflow_experiment,
        commit_hash,
        PUBLISH.out.run_manifest,
        PUBLISH.out.run_params,
        BUILD_JSONS.out.contract_data
    )
}
