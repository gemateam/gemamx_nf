nextflow.enable.dsl = 2

/*
 * ============================================================================
 * gemamx_nf — GEMA MX · Pipeline V2.1 (Romero-Córdoba 2021 HM) — solo CPU
 * Nextflow DSL2 · Docker · MLflow
 *
 * Independiente de main_v2.nf. Diferencias:
 *
 *   1. UN WT POR VARIANTE (PREDICT_STRUCTURE_WT_PAIR). Cada variante se compara
 *      contra un WT centrado en su misma posición, así que ALIGN_WT_MUT ya no
 *      falla cuando un gen tiene variantes en regiones distintas (PIK3CA:
 *      E542K vs H1047R). Ya no hace falta limitar max_variants.
 *   2. Docking del WT solo UNA vez por gen: el de la primera variante
 *      priorizada, registrado como `<GEN>_WT` (misma clave que lee la webapp).
 *      El resto de WT se usa únicamente para RMSD (docking en CPU es caro).
 *   3. Validación temprana de target_drug_map / binding_sites: aborta al inicio
 *      si el mapa cita fármacos fuera del catálogo o genes sin sitio.
 *   4. Sin GPU: structures_mode = precomputed | esmfold. `boltz` se rechaza.
 *
 * Contrato aditivo: structural_metrics.json añade `wt_structure`; el manifest
 * añade `<GEN>_WT_<CAMBIO>` y mantiene `<GEN>_WT` como alias canónico.
 *
 * Uso:
 *   nextflow run main_v2_1.nf -profile docker,romero-v2,v2_1 -name romero_v2_1
 *   bash tests/run_smoke_v2_1.sh            # prueba de humo aislada
 * ============================================================================
 */

include { INGEST_ROMERO; EXTRACT_CLINICAL; BUILD_CLINICAL_SUMMARY }  from './modules/clinical/main'
include { FETCH_FASTA_WT; FETCH_FASTA_MUT }                         from './modules/fasta/main'
include { ALIGN_WT_MUT }                                           from './modules/structure/main'
include { PREDICT_STRUCTURE_WT_PAIR; PREDICT_STRUCTURE_MUT_PAIR }   from './modules/structure/v2_1'
include { PREP_LIGAND; PREP_RECEPTOR; DOCK_CENTER; RUN_VINA; loadPairing; loadSites } from './modules/docking/main'
include { BUILD_JSONS; PUBLISH }                                    from './modules/metrics/main'
include { LOG_MLFLOW }                                              from './modules/mlflow/main'

/*
 * Ventana de plegado para una variante: centro y tamaño que cubren a la vez el
 * bolsillo (assets/binding_sites.csv) y el residuo mutado.
 *
 * `--window W` cubre [centro-W, centro+W-1]; para contener `low..high` hace
 * falta W >= max(centro-low, high-centro+1). ESMFold admite 390 aa, así que si
 * el bloque no cabe se vuelve a centrar en la mutación (comportamiento V2) y
 * `dock_center.py` marcará site_covered=false.
 *
 * Devuelve [centro, ventana, cubre_bolsillo].
 */
def foldWindow(Map sites, int domainWindow, String gene, String pc) {
    def m = (pc =~ /^[A-Za-z](\d+)[A-Za-z]$/)
    def pos = m.matches() ? (m[0][1] as Integer) : 0
    def residues = (sites[gene] ?: '')
        .tokenize(';').findAll { it?.trim() }.collect { it.trim() as Integer }
    if (pos <= 0 || residues.isEmpty()) {
        return [pos, domainWindow, false]
    }
    def low  = Math.min(pos, residues.min())
    def high = Math.max(pos, residues.max())
    if (high - low + 1 > 388) {
        return [pos, domainWindow, false]
    }
    def center = (low + high).intdiv(2)
    def window = Math.max(domainWindow, Math.max(center - low, high - center + 1))
    return [center, window, true]
}

workflow {

    if (params.structures_mode == 'boltz') {
        error "main_v2_1.nf es solo CPU: usa --structures_mode precomputed o esmfold (boltz requiere GPU)."
    }

    // ── Commit del repositorio ─────────────────────────────────────────────
    def commit_hash = 'unknown'
    try {
        def proc = ['git', 'rev-parse', 'HEAD'].execute()
        proc.waitFor()
        if (proc.exitValue() == 0) commit_hash = proc.text.trim()
    } catch (Exception e) { /* sin git */ }

    def source_snapshot = file("${workDir}/mlflow-source-code/${workflow.runName}")
    def snapshot_proc = [
        'python3', "${projectDir}/bin/snapshot_mlflow_sources.py".toString(),
        '--repo', projectDir.toString(), '--out', source_snapshot.toString(),
        '--workflow', 'main_v2_1.nf', '--git-commit', commit_hash
    ].execute()
    snapshot_proc.waitFor()
    if (snapshot_proc.exitValue() != 0) {
        error("No se pudo crear el snapshot de código para MLflow: ${snapshot_proc.text}")
    }
    def ch_source_snapshot = Channel.value(source_snapshot)

    // ── Archivos de entrada ────────────────────────────────────────────────
    def maf_xlsx          = file(params.romero_maf,      checkIfExists: true)
    def drivers_xlsx      = file(params.romero_drivers,  checkIfExists: true)
    def clinical_xlsx     = file(params.romero_clinical, checkIfExists: true)
    def drug_catalog_file = file(params.drug_catalog,    checkIfExists: true)

    // ── Validación temprana: mapa fármaco-diana y sitios de unión ──────────
    // pairing = null reproduce V2 (producto cartesiano receptores × fármacos).
    def pairing = params.target_drug_map ? loadPairing(params.target_drug_map.toString()) : null
    if (pairing) {
        def catalog_names = drug_catalog_file.readLines().tail().collect { it.split(',')[0].trim() } as Set
        def unknown = pairing.values().collectMany { it.keySet() }.findAll { !(it in catalog_names) }.unique()
        if (unknown) {
            error "target_drug_map referencia fármacos que no están en drug_catalog: ${unknown}"
        }
        if (params.box_center_mode == 'binding_site') {
            if (!params.binding_sites) {
                error "box_center_mode=binding_site requiere --binding_sites"
            }
            def sites = loadSites(params.binding_sites.toString(), params.binding_site_name)
            def no_site = pairing.keySet().findAll { !sites.containsKey(it) }
            if (no_site) {
                error "binding_sites no define '${params.binding_site_name}' para genes con pares de docking: ${no_site}"
            }
        }
    }

    // ── M1/M2 — Ingestión desde XLSX nativos de Romero ────────────────────
    INGEST_ROMERO(maf_xlsx, drivers_xlsx, clinical_xlsx)

    // ── M5a/M5b — Metadatos y resumen clínico por variante ─────────────────
    EXTRACT_CLINICAL(clinical_xlsx)

    BUILD_CLINICAL_SUMMARY(
        INGEST_ROMERO.out.raw_mutations,
        EXTRACT_CLINICAL.out.clinical_metadata,
        INGEST_ROMERO.out.top_variants
    )

    // ── Variantes priorizadas → [gene, protein_change, rank] ───────────────
    // `rank` fija el WT canónico de forma determinista (orden de top_variants),
    // en vez de depender del orden en que groupTuple agrupa las variantes.
    def ch_variant_rows = INGEST_ROMERO.out.top_variants
        .flatMap { json_file ->
            def json = new groovy.json.JsonSlurper().parse(json_file)
            json.withIndex().collect { row, i ->
                tuple(row.hugo_symbol ?: row.gene, row.protein_change, i)
            }
        }
        .unique()

    def ch_variants = ch_variant_rows
        .map { gene, pc, rank -> tuple(gene, pc) }
        .unique()

    def ch_genes = ch_variants
        .map { gene, pc -> gene }
        .unique()

    // WT "canónico" por gen = variante con menor rank (la primera priorizada).
    // Es el único WT que se dockea, bajo el id <GEN>_WT.
    def ch_canonical = ch_variant_rows
        .groupTuple()
        .map { gene, pcs, ranks ->
            def i = ranks.indexOf(ranks.min())
            tuple(gene, pcs[i])
        }

    // ── Ventana de plegado: bolsillo + mutación ────────────────────────────
    // Ver foldWindow() al principio del script.
    def sites = (params.box_center_mode == 'binding_site' && params.binding_sites)
        ? loadSites(params.binding_sites.toString(), params.binding_site_name)
        : [:]

    // ── FASTA ─────────────────────────────────────────────────────────────
    def fasta_dir = params.fasta_dir ? file(params.fasta_dir) : null

    def ch_wt_fasta_input = ch_genes
        .map { gene ->
            def precomp = fasta_dir ? file("${fasta_dir}/${gene}_WT.fasta") : []
            def precomp_exists = (precomp instanceof java.nio.file.Path && precomp.exists()) ? precomp : []
            tuple(gene, precomp_exists)
        }

    FETCH_FASTA_WT(ch_wt_fasta_input)

    def ch_mut_with_wt = ch_variants
        .combine(FETCH_FASTA_WT.out.wt_fasta, by: 0)
        .map { gene, pc, fasta_wt ->
            def precomp = fasta_dir ? file("${fasta_dir}/${gene}_${pc}.fasta") : []
            def precomp_exists = (precomp instanceof java.nio.file.Path && precomp.exists()) ? precomp : []
            tuple(gene, pc, fasta_wt, precomp_exists)
        }

    FETCH_FASTA_MUT(ch_mut_with_wt)

    // ── ESTRUCTURAS 3D ────────────────────────────────────────────────────
    def struct_dir = params.structures_dir ? file(params.structures_dir) : null

    // WT por variante: precomputado esperado en <structures_dir>/WT__<GEN>_<CAMBIO>.pdb
    // La ventana (centro y tamaño) se calcula una sola vez por variante; ver
    // foldWindow() arriba para la aritmética y docs/V2_1.md para los ejemplos.
    def ch_fold_window = ch_variants
        .map { gene, pc ->
            def (center, window, covers) = foldWindow(sites, params.domain_window as int, gene, pc)
            tuple(gene, pc, center, window)
        }

    def ch_wt_pair_input = ch_variants
        .combine(FETCH_FASTA_WT.out.wt_fasta, by: 0)
        .map { gene, pc, fasta ->
            def pdb = struct_dir ? file("${struct_dir}/WT__${gene}_${pc}.pdb") : []
            tuple(gene, pc, fasta,
                  (pdb instanceof java.nio.file.Path && pdb.exists()) ? pdb : [])
        }
        .join(ch_fold_window, by: [0, 1])

    PREDICT_STRUCTURE_WT_PAIR(ch_wt_pair_input)

    def ch_mut_struct_input = FETCH_FASTA_MUT.out.mut_fasta
        .map { gene, pc, fasta ->
            def pdb  = struct_dir ? file("${struct_dir}/${gene}_${pc}.pdb")  : []
            def meta = struct_dir ? file("${struct_dir}/${gene}_${pc}.json") : []
            tuple(gene, pc, fasta,
                  (pdb instanceof java.nio.file.Path && pdb.exists()) ? pdb  : [],
                  (meta instanceof java.nio.file.Path && meta.exists()) ? meta : [])
        }
        .join(ch_fold_window, by: [0, 1])

    PREDICT_STRUCTURE_MUT_PAIR(ch_mut_struct_input)

    // ── RMSD: cada variante contra SU WT (join por gen+cambio, no cross) ───
    def ch_wt_keyed = PREDICT_STRUCTURE_WT_PAIR.out.wt_struct
        .map { gene, pc, pdb, meta -> tuple("${gene}_${pc}".toString(), gene, pc, pdb, meta) }

    def ch_mut_keyed = PREDICT_STRUCTURE_MUT_PAIR.out.mut_struct
        .map { gene, pc, pdb, meta -> tuple("${gene}_${pc}".toString(), pdb, meta) }

    def ch_align_input = ch_wt_keyed
        .join(ch_mut_keyed)
        .map { id, gene, pc, wt_pdb, wt_meta, mut_pdb, mut_meta ->
            tuple(gene, pc, wt_pdb, wt_meta, mut_pdb, mut_meta)
        }

    ALIGN_WT_MUT(ch_align_input)

    // ── LIGANDOS Y RECEPTORES ─────────────────────────────────────────────
    def ch_drugs = Channel.fromPath(drug_catalog_file)
        .splitCsv(header: true)
        .map { row -> tuple(row.name, drug_catalog_file) }

    PREP_LIGAND(ch_drugs)

    // Solo el WT canónico entra a docking, con id <GEN>_WT.
    def ch_wt_receptors = PREDICT_STRUCTURE_WT_PAIR.out.wt_struct
        .join(ch_canonical, by: [0, 1])
        .map { gene, pc, pdb, meta -> tuple("${gene}_WT".toString(), pdb, meta) }

    def ch_receptors_all = ch_wt_receptors
        .mix(
            PREDICT_STRUCTURE_MUT_PAIR.out.mut_struct
                .map { gene, pc, pdb, meta -> tuple("${gene}_${pc}".toString(), pdb, meta) }
        )

    // Solo dianas con pares definidos en target_drug_map.
    def ch_receptors = pairing
        ? ch_receptors_all.filter { id, pdb, meta -> pairing.containsKey(id.tokenize('_')[0]) }
        : ch_receptors_all

    PREP_RECEPTOR(ch_receptors)
    DOCK_CENTER(PREP_RECEPTOR.out.receptor_pdbqt)

    // Receptores × ligandos, solo pares del mapa (on_target + controles).
    def ch_docking_pairs = DOCK_CENTER.out.target_box
        .combine(PREP_LIGAND.out.ligand_pdbqt)
        .filter { target_id, receptor, box, drug, ligand ->
            !pairing || pairing[target_id.tokenize('_')[0]]?.containsKey(drug)
        }

    // ── AUTODOCK VINA ─────────────────────────────────────────────────────
    RUN_VINA(ch_docking_pairs)

    // ── BUILD JSONS ───────────────────────────────────────────────────────
    def ch_struct_files = PREDICT_STRUCTURE_WT_PAIR.out.wt_struct
        .flatMap { gene, pc, pdb, meta -> [pdb, meta] }
        .mix(PREDICT_STRUCTURE_WT_PAIR.out.wt_cif)
        .mix(
            PREDICT_STRUCTURE_MUT_PAIR.out.mut_struct
                .flatMap { gene, pc, pdb, meta -> [pdb, meta] }
        )
        .mix(PREDICT_STRUCTURE_MUT_PAIR.out.mut_cif)
        .collect()

    def ch_vina_files = RUN_VINA.out.vina_summary
        .map { target, drug, summary -> summary }
        .mix(RUN_VINA.out.vina_out_pdbqt)
        .collect()

    def ch_complex_files = RUN_VINA.out.vina_complex_pdb.collect()

    def ch_clinical_files = BUILD_CLINICAL_SUMMARY.out.clinical_summary
        .mix(EXTRACT_CLINICAL.out.clinical_metadata)
        .mix(INGEST_ROMERO.out.ingest_metadata)
        .collect()

    BUILD_JSONS(
        INGEST_ROMERO.out.top_variants,
        INGEST_ROMERO.out.raw_mutations,
        INGEST_ROMERO.out.mutation_stats,
        drug_catalog_file,
        ch_struct_files,
        ALIGN_WT_MUT.out.rmsd_json.collect(),
        ch_vina_files,
        ch_complex_files,
        ch_clinical_files,
        workflow.runName
    )

    // ── PUBLISH ───────────────────────────────────────────────────────────
    PUBLISH(
        BUILD_JSONS.out.top_variants_out,
        BUILD_JSONS.out.structural_metrics,
        BUILD_JSONS.out.manifest_structures,
        BUILD_JSONS.out.raw_mutations_out,
        BUILD_JSONS.out.mutation_stats_out,
        BUILD_JSONS.out.vina_affinities,
        BUILD_JSONS.out.data_ingest_out,
        workflow.runName,
        commit_hash
    )

    // ── LOG MLFLOW ────────────────────────────────────────────────────────
    if (params.mlflow_enabled.toString().toBoolean()) {
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
                .mix(BUILD_JSONS.out.data_ingest_out)
                .collect(),
            ch_source_snapshot
        )
    } else {
        log.info 'MLflow disabled; skipping run registration'
    }

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
            if (params.mlflow_enabled.toString().toBoolean()) {
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
            } else {
                log.info 'MLflow disabled; skipping report upload'
            }
        }
    }
}
