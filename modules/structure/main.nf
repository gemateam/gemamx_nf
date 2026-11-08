process PREDICT_STRUCTURE_WT {
    tag "${gene}_WT"
    container "${params.structures_mode == 'boltz' ? params.image_gpu : params.image_cpu}"

    input:
    tuple val(gene), path(fasta), path(precomputed_pdb), path(precomputed_meta), val(window_center)

    output:
    tuple val(gene), path("${gene}_WT.pdb"), path("${gene}_WT.json"), emit: wt_struct
    path "${gene}_WT.cif", optional: true, emit: wt_cif

    script:
    def mode = params.structures_mode
    if (mode == 'boltz') {
        error "El backend 'boltz' requiere GPU (en YUCA: AMD MI210 de 64 GB con ROCm 6.2.3) y la imagen ${params.image_gpu}. " +
              "Está implementado en modules/structure/boltz.nf pero NO cableado en main.nf: " +
              "ver docs/BOLTZ_HPC.md § 5. Activación."
    }
    def has_precomputed = precomputed_pdb && precomputed_pdb.toString() != 'null'
    def backend = (mode == 'precomputed' && !has_precomputed) ? 'esmfold' : mode
    def precomp_arg = (backend == 'precomputed') ? "--structure ${precomputed_pdb}" : ""
    def model_window = (backend == 'esmfold' && mode == 'precomputed') ? Math.min(params.domain_window, 120) : params.domain_window
    def fallback_args = backend != mode ? "--timeout 300 --retries 5" : ""
    def backend_note = backend != mode ? "echo 'WARN: falta estructura WT precomputada para ${gene}; se usará ESMFold' >&2" : ""
    // WT no tiene mutación: con esmfold la ventana se centra en la posición
    // del evento que se compara (la primera mutación conocida del gen).
    def center_arg = (window_center && window_center > 0) ? "--window-center ${window_center}" : ""
    """
    predict_structure.py \\
        --fasta "${fasta}" \\
        --gene "${gene}" \\
        --protein-change "WT" \\
        --role "wt" \\
        --backend "${backend}" \\
        ${precomp_arg} \\
        ${center_arg} \\
        --window ${model_window} \\
        ${fallback_args} \\
        --out "${gene}_WT.pdb" \\
        --out-cif "${gene}_WT.cif" \\
        --meta "${gene}_WT.json"
    """

    stub:
    """
    echo "ATOM      1  CA  MET A   1       0.000   0.000   0.000  1.00 80.00           C" > "${gene}_WT.pdb"
    echo '{"gene":"${gene}","protein_change":"WT","model_start":1,"model_resseq_start":1,"model_resseq_end":10,"mutation_resseq_model":null,"mean_plddt":80.0,"plddt_source":"esmfold","structure_cif":"${gene}_WT.cif"}' > "${gene}_WT.json"
    touch "${gene}_WT.cif"
    """
}

process PREDICT_STRUCTURE_MUT {
    tag "${gene}_${protein_change}"
    container "${params.structures_mode == 'boltz' ? params.image_gpu : params.image_cpu}"

    input:
    tuple val(gene), val(protein_change), path(fasta), path(precomputed_pdb), path(precomputed_meta)

    output:
    tuple val(gene), val(protein_change), path("${gene}_${protein_change}.pdb"), path("${gene}_${protein_change}.json"), emit: mut_struct
    path "${gene}_${protein_change}.cif", optional: true, emit: mut_cif

    script:
    def mode = params.structures_mode
    if (mode == 'boltz') {
        error "El backend 'boltz' requiere GPU (en YUCA: AMD MI210 de 64 GB con ROCm 6.2.3) y la imagen ${params.image_gpu}. " +
              "Está implementado en modules/structure/boltz.nf pero NO cableado en main.nf: " +
              "ver docs/BOLTZ_HPC.md § 5. Activación."
    }
    def has_precomputed = precomputed_pdb && precomputed_pdb.toString() != 'null'
    def backend = (mode == 'precomputed' && !has_precomputed) ? 'esmfold' : mode
    def precomp_arg = (backend == 'precomputed') ? "--structure ${precomputed_pdb}" : ""
    def model_window = (backend == 'esmfold' && mode == 'precomputed') ? Math.min(params.domain_window, 120) : params.domain_window
    def fallback_args = backend != mode ? "--timeout 300 --retries 5" : ""
    def backend_note = backend != mode ? "echo 'WARN: falta estructura precomputada para ${gene}_${protein_change}; se usará ESMFold' >&2" : ""
    """
    ${backend_note}
    predict_structure.py \\
        --fasta "${fasta}" \\
        --gene "${gene}" \\
        --protein-change "${protein_change}" \\
        --role "mut" \\
        --backend "${backend}" \\
        ${precomp_arg} \\
        --window ${model_window} \\
        ${fallback_args} \\
        --out "${gene}_${protein_change}.pdb" \\
        --out-cif "${gene}_${protein_change}.cif" \\
        --meta "${gene}_${protein_change}.json"
    """

    stub:
    """
    echo "ATOM      1  CA  MET A   1       0.000   0.000   0.000  1.00 80.00           C" > "${gene}_${protein_change}.pdb"
    echo '{"gene":"${gene}","protein_change":"${protein_change}","model_start":1,"model_resseq_start":1,"model_resseq_end":10,"mutation_resseq_model":5,"mean_plddt":80.0,"plddt_source":"esmfold","structure_cif":"${gene}_${protein_change}.cif"}' > "${gene}_${protein_change}.json"
    touch "${gene}_${protein_change}.cif"
    """
}

process ALIGN_WT_MUT {
    tag "${gene}_${protein_change}"
    container "${params.image_cpu}"

    input:
    tuple val(gene), val(protein_change), path(wt_pdb), path(wt_meta), path(mut_pdb), path(mut_meta)

    output:
    path "${gene}_${protein_change}_rmsd.json", emit: rmsd_json

    script:
    """
    align_wt_mut.py \\
        --wt "${wt_pdb}" \\
        --mut "${mut_pdb}" \\
        --wt-meta "${wt_meta}" \\
        --mut-meta "${mut_meta}" \\
        --out "${gene}_${protein_change}_rmsd.json"
    """

    stub:
    """
    echo '{"variant":"${gene}_${protein_change}","gene":"${gene}","protein_change":"${protein_change}","rmsd_all":0.45,"rmsd_active":0.32,"matched_pairs":10}' > "${gene}_${protein_change}_rmsd.json"
    """
}
