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

    // 2b. Snapshot clínico (opcional). Con clinical_ingest y sin snapshot, INGEST
    // descarga RACE/ETHNICITY/AGE de cBioPortal; con clinical_json no hay red.
    def ch_clinical_input = params.clinical_json
        ? Channel.fromPath(params.clinical_json, checkIfExists: true)
        : Channel.value([])

    // 3. Catálogo de fármacos
    def drug_catalog_file = file(params.drug_catalog, checkIfExists: true)

    // ── INGEST ────────────────────────────────────────────────────────────────
    INGEST(ch_mutations_input, ch_clinical_input)

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

    // Ventana de ESMFold para WT: el WT no tiene mutación propia, así que se
    // centra en la primera mutación conocida del gen. Sin esto, una proteína
    // larga (p. ej. PIK3CA, 1068 aa) no se puede plegar con la API (límite 390)
    // y WT/MUT cubrirían regiones distintas (RMSD no comparable).
    def ch_gene_center = ch_variants
        .map { gene, pc ->
            def m = (pc =~ /^[A-Za-z](\d+)[A-Za-z]$/)
            tuple(gene, m.matches() ? (m[0][1] as Integer) : 0)
        }
        .groupTuple()
        .map { gene, positions -> tuple(gene, positions.find { it > 0 } ?: 0) }

    // ── FASTA ─────────────────────────────────────────────────────────────────
    // Cuando fasta_dir está definido, se usan FASTA precomputados (sin red).
    def fasta_dir = params.fasta_dir ? file(params.fasta_dir) : null

    def ch_wt_fasta_input = ch_genes
        .map { gene ->
            def precomp = fasta_dir ? file("${fasta_dir}/${gene}_WT.fasta") : []
            def precomp_exists = (precomp instanceof java.nio.file.Path && precomp.exists()) ? precomp : []
            tuple(gene, precomp_exists)
        }

    FETCH_FASTA_WT(ch_wt_fasta_input)

    // Combinar por gene: [gene, fasta_wt] × [gene, pc] → [gene, pc, fasta_wt, precomp_mut]
    def ch_mut_with_wt = ch_variants
        .combine(FETCH_FASTA_WT.out.wt_fasta, by: 0)
        .map { gene, pc, fasta_wt ->
            def precomp = fasta_dir ? file("${fasta_dir}/${gene}_${pc}.fasta") : []
            def precomp_exists = (precomp instanceof java.nio.file.Path && precomp.exists()) ? precomp : []
            tuple(gene, pc, fasta_wt, precomp_exists)
        }

    FETCH_FASTA_MUT(ch_mut_with_wt)

    // ── ESTRUCTURAS 3D ────────────────────────────────────────────────────────
    def struct_dir = params.structures_dir ? file(params.structures_dir) : null

    def ch_wt_struct_input = FETCH_FASTA_WT.out.wt_fasta
        .join(ch_gene_center)
        .map { gene, fasta, window_center ->
            def pdb  = struct_dir ? file("${struct_dir}/${gene}_WT.pdb")  : []
            def meta = struct_dir ? file("${struct_dir}/${gene}_WT.json") : []
            tuple(gene, fasta,
                  (pdb instanceof java.nio.file.Path && pdb.exists()) ? pdb  : [],
                  (meta instanceof java.nio.file.Path && meta.exists()) ? meta : [],
                  window_center)
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

    // Alineamiento WT vs MUT: emparejar por GEN, no producto cartesiano.
    // `.cross()` generaba además pares WT(A)×MUT(B); ALIGN_WT_MUT abortaba con
    // "genes distintos" (bin/align_wt_mut.py:66). `combine(by: 0)` da una WT por
    // gen × sus variantes, que es el mismo patrón que usa FETCH_FASTA_MUT arriba.
    def ch_align_input = PREDICT_STRUCTURE_WT.out.wt_struct
        .combine(PREDICT_STRUCTURE_MUT.out.mut_struct, by: 0)
        .map { gene, wt_pdb, wt_meta, pc, mut_pdb, mut_meta ->
            tuple(gene, pc, wt_pdb, wt_meta, mut_pdb, mut_meta)
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
    // Recolectar todos los PDB+JSON+CIF de estructuras en una sola lista
    def ch_struct_files = PREDICT_STRUCTURE_WT.out.wt_struct
        .flatMap { gene, pdb, meta -> [pdb, meta] }
        .mix(PREDICT_STRUCTURE_WT.out.wt_cif)
        .mix(
            PREDICT_STRUCTURE_MUT.out.mut_struct
                .flatMap { gene, pc, pdb, meta -> [pdb, meta] }
        )
        .mix(PREDICT_STRUCTURE_MUT.out.mut_cif)
        .collect()

    // Recolectar resúmenes Vina (summary + out.pdbqt) y complejos PDB
    def ch_vina_files = RUN_VINA.out.vina_summary
        .map { target, drug, summary -> summary }
        .mix(RUN_VINA.out.vina_out_pdbqt)
        .collect()

    def ch_complex_files = RUN_VINA.out.vina_complex_pdb.collect()

    // Clínica opcional (RACE/ETHNICITY/AGE). Si clinical_ingest está apagado,
    // las salidas opcionales de INGEST no existen y la lista queda vacía, que es
    // el mismo valor que recibía BUILD_JSONS antes de este cambio.
    def ch_clinical_files = INGEST.out.clinical_metadata
        .mix(INGEST.out.clinical_summary)
        .collect()
        .ifEmpty([])

    BUILD_JSONS(
        INGEST.out.top_variants,
        INGEST.out.raw_mutations,
        INGEST.out.mutation_stats,
        drug_catalog_file,
        ch_struct_files,
        ALIGN_WT_MUT.out.rmsd_json.collect(),
        ch_vina_files,
        ch_complex_files,
        ch_clinical_files,
        workflow.runName
    )

    // ── PUBLISH ───────────────────────────────────────────────────────────────
    PUBLISH(
        BUILD_JSONS.out.top_variants_out,
        BUILD_JSONS.out.structural_metrics,
        BUILD_JSONS.out.manifest_structures,
        BUILD_JSONS.out.raw_mutations_out,
        BUILD_JSONS.out.mutation_stats_out,
        BUILD_JSONS.out.vina_affinities,
        workflow.runName,
        commit_hash
    )

    // ── LOG MLFLOW ────────────────────────────────────────────────────────────
    LOG_MLFLOW(
        workflow.runName,
        params.mlflow_tracking_uri,
        params.mlflow_experiment,
        commit_hash,
        PUBLISH.out.run_manifest,
        PUBLISH.out.run_params,
        BUILD_JSONS.out.top_variants_out
            .mix(BUILD_JSONS.out.structural_metrics)
            .mix(BUILD_JSONS.out.vina_affinities)
            .collect()
    )

    /*
     * Subida automática de los reportes HTML (report, timeline, dag) al run padre
     * de MLflow. Se lanza al terminar la corrida, en segundo plano, porque Nextflow
     * escribe los HTML justo después de este punto; bin/nf_reports_hook.sh espera
     * a que existan y los adjunta al run con `upload_nf_reports.py`.
     *
     * Los reportes ya están activos en nextflow.config, así que cualquier
     * `nextflow run ...` deja los HTML adjuntos sin flags ni wrappers.
     * (En la sintaxis estricta de Nextflow 26+, el handler va dentro del workflow.)
     */
    workflow.onComplete = {
        if (workflow.stubRun) {
            log.info 'stub-run: no se promueve el contrato ni se suben reportes'
        } else {
            def outDir  = new File(params.outdir.toString()).absolutePath
            def infoDir = new File(outDir, 'pipeline_info')
            infoDir.mkdirs()

            // 1. Contrato vigente: conserva runs/<run> y promueve data/ con un
            //    reemplazo atómico. Corre en el host: un proceso en contenedor
            //    no ve las rutas del outdir.
            if (workflow.success) {
                try {
                    def pc = ['bash', "${projectDir}/bin/publish_contract_hook.sh".toString(),
                              '--outdir', outDir,
                              '--run-name', workflow.runName,
                              '--archive', params.publish_run_archive.toString(),
                              '--restart-container',
                              params.webapp_restart ? params.webapp_container.toString() : '',
                              '--bin', "${projectDir}/bin".toString()]
                    def pb = new ProcessBuilder(pc)
                    pb.redirectErrorStream(true)
                    pb.redirectOutput(ProcessBuilder.Redirect.appendTo(new File(infoDir, 'publish.log')))
                    def proc = pb.start()
                    proc.waitFor()
                    if (proc.exitValue() == 0) {
                        log.info "Contrato vigente actualizado en ${outDir}/data (${workflow.runName})"
                    } else {
                        log.error "No se pudo promover el contrato (código ${proc.exitValue()}): " +
                                  "data/ sigue con la corrida anterior. Ver ${infoDir}/publish.log"
                    }
                } catch (Exception e) {
                    log.error "No se pudo lanzar la promoción del contrato: ${e.message}"
                }
            } else {
                log.warn 'La corrida falló: no se toca data/ ni se archiva la corrida'
            }

            // 2. Reportes HTML (report, timeline, dag) → run padre de MLflow.
            try {
                def cmd = ['bash', "${projectDir}/bin/nf_reports_hook.sh".toString(),
                           '--outdir', outDir,
                           '--run-name', workflow.runName,
                           '--experiment', params.mlflow_experiment,
                           '--host-uri', params.mlflow_host_uri,
                           '--docker-uri', params.mlflow_docker_uri,
                           '--docker-network', params.mlflow_docker_network,
                           '--image', params.image_cpu,
                           '--bin', "${projectDir}/bin".toString()]
                def pb = new ProcessBuilder(cmd)
                pb.redirectErrorStream(true)
                pb.redirectOutput(ProcessBuilder.Redirect.appendTo(new File(infoDir, 'upload.log')))
                pb.start()
                log.info "Reportes HTML -> MLflow: subida en segundo plano (${workflow.runName})"
            } catch (Exception e) {
                log.warn "No se pudo lanzar la subida de reportes a MLflow: ${e.message}"
            }
        }
    }
}
