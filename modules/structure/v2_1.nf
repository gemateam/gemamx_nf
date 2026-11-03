/*
 * Módulo de estructura V2.1 — un WT por variante, ventana que cubre el bolsillo.
 *
 * En V2 había un único WT por gen y la ventana del fragmento dependía de la
 * primera mutación del gen: con otra variante en una región distinta, WT y MUT
 * no compartían residuos y ALIGN_WT_MUT fallaba. Aquí cada variante tiene su
 * propio WT, centrado en su misma posición (`predict_structure.py --wt-for`).
 *
 * V2.1 añade la ventana de docking: el orquestador calcula un centro que cubre
 * a la vez el bolsillo (assets/binding_sites.csv) y el residuo mutado, y lo pasa
 * a ambos procesos. Así el receptor que se acopla sí contiene el sitio de unión.
 * Si el bolsillo y la mutación no caben en el límite de ESMFold (390 aa), el
 * orquestador vuelve a centrar en la mutación y lo registra; `dock_center.py`
 * marcará `site_covered=false`.
 *
 * Solo CPU: backends `precomputed` (por defecto) y `esmfold` (API pública).
 * El backend `boltz` requiere GPU y no está disponible en este flujo.
 *
 * PREDICT_STRUCTURE_MUT y ALIGN_WT_MUT se reutilizan de ./main sin cambios.
 */

process PREDICT_STRUCTURE_WT_PAIR {
    tag "${gene}_WT_${protein_change}"
    container "${params.image_cpu}"

    input:
    tuple val(gene), val(protein_change), path(fasta), path(precomputed_pdb), val(window_center), val(window)

    output:
    tuple val(gene), val(protein_change), path("${gene}_WT_${protein_change}.pdb"), path("${gene}_WT_${protein_change}.json"), emit: wt_struct
    path "${gene}_WT_${protein_change}.cif", optional: true, emit: wt_cif

    script:
    def mode = params.structures_mode
    if (mode == 'boltz') {
        error "main_v2_1.nf solo soporta CPU (structures_mode = precomputed | esmfold). " +
              "El backend 'boltz' requiere GPU: ver docs/BOLTZ_HPC.md."
    }
    def precomp_arg = (mode == 'precomputed' && precomputed_pdb) ? "--structure ${precomputed_pdb}" : ""
    def center_arg = (window_center && window_center > 0) ? "--window-center ${window_center}" : ""
    def out = "${gene}_WT_${protein_change}"
    """
    predict_structure.py \\
        --fasta "${fasta}" \\
        --gene "${gene}" \\
        --protein-change "WT" \\
        --wt-for "${protein_change}" \\
        --role "wt" \\
        --backend "${mode}" \\
        ${precomp_arg} \\
        ${center_arg} \\
        --window ${window} \\
        --out "${out}.pdb" \\
        --out-cif "${out}.cif" \\
        --meta "${out}.json"
    """

    stub:
    def out = "${gene}_WT_${protein_change}"
    """
    echo "ATOM      1  CA  MET A   1       0.000   0.000   0.000  1.00 80.00           C" > "${out}.pdb"
    echo '{"gene":"${gene}","protein_change":"WT","role":"wt","wt_for":"${gene}_${protein_change}","structure_file":"${out}.pdb","model_start":1,"model_resseq_start":1,"model_resseq_end":10,"mean_plddt":80.0,"plddt_mean":80.0,"structure_cif":"${out}.cif"}' > "${out}.json"
    touch "${out}.cif"
    """
}

/*
 * MUT con la MISMA ventana que su WT.
 *
 * `predict_structure.py` centra la ventana en la mutación por defecto; aquí se
 * le pasa el centro calculado por el orquestador (bolsillo + mutación) para que
 * WT y MUT cubran exactamente la misma región y el receptor contenga el sitio
 * de unión. La aridad es distinta de PREDICT_STRUCTURE_MUT a propósito: así V1 y
 * V2 (main.nf, main_v2.nf) no cambian.
 */
process PREDICT_STRUCTURE_MUT_PAIR {
    tag "${gene}_${protein_change}"
    container "${params.image_cpu}"

    input:
    tuple val(gene), val(protein_change), path(fasta), path(precomputed_pdb), path(precomputed_meta), val(window_center), val(window)

    output:
    tuple val(gene), val(protein_change), path("${gene}_${protein_change}.pdb"), path("${gene}_${protein_change}.json"), emit: mut_struct
    path "${gene}_${protein_change}.cif", optional: true, emit: mut_cif

    script:
    def mode = params.structures_mode
    if (mode == 'boltz') {
        error "main_v2_1.nf solo soporta CPU (structures_mode = precomputed | esmfold). " +
              "El backend 'boltz' requiere GPU: ver docs/BOLTZ_HPC.md."
    }
    def precomp_arg = (mode == 'precomputed' && precomputed_pdb) ? "--structure ${precomputed_pdb}" : ""
    def center_arg = (window_center && window_center > 0) ? "--window-center ${window_center}" : ""
    """
    predict_structure.py \\
        --fasta "${fasta}" \\
        --gene "${gene}" \\
        --protein-change "${protein_change}" \\
        --role "mut" \\
        --backend "${mode}" \\
        ${precomp_arg} \\
        ${center_arg} \\
        --window ${window} \\
        --out "${gene}_${protein_change}.pdb" \\
        --out-cif "${gene}_${protein_change}.cif" \\
        --meta "${gene}_${protein_change}.json"
    """

    stub:
    """
    echo "ATOM      1  CA  MET A   1       0.000   0.000   0.000  1.00 80.00           C" > "${gene}_${protein_change}.pdb"
    echo '{"gene":"${gene}","protein_change":"${protein_change}","role":"mut","structure_file":"${gene}_${protein_change}.pdb","model_start":1,"model_resseq_start":1,"model_resseq_end":10,"mutation_resseq_model":5,"mean_plddt":80.0,"plddt_mean":80.0,"structure_cif":"${gene}_${protein_change}.cif"}' > "${gene}_${protein_change}.json"
    touch "${gene}_${protein_change}.cif"
    """
}
