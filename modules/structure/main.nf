process PREDICT_STRUCTURE_WT {
    tag "${gene}_WT"
    container "${params.structures_mode == 'boltz' ? params.image_gpu : params.image_cpu}"

    input:
    tuple val(gene), path(fasta), path(precomputed_pdb), path(precomputed_meta)

    output:
    tuple val(gene), path("${gene}_WT.pdb"), path("${gene}_WT.json"), emit: wt_struct

    script:
    def mode = params.structures_mode
    if (mode == 'boltz') {
        error "El backend 'boltz' requiere GPU y la imagen ${params.image_gpu} no está autorizada/disponible en local."
    }
    def precomp_arg = (mode == 'precomputed' && precomputed_pdb) ? "--structure ${precomputed_pdb}" : ""
    """
    predict_structure.py \\
        --fasta "${fasta}" \\
        --gene "${gene}" \\
        --protein-change "WT" \\
        --role "wt" \\
        --backend "${mode}" \\
        ${precomp_arg} \\
        --window ${params.domain_window} \\
        --out "${gene}_WT.pdb" \\
        --meta "${gene}_WT.json"
    """

    stub:
    """
    echo "ATOM      1  CA  MET A   1       0.000   0.000   0.000  1.00 80.00           C" > "${gene}_WT.pdb"
    echo '{"gene":"${gene}","protein_change":"WT","model_start":1,"model_resseq_start":1,"model_resseq_end":10,"mutation_resseq_model":null,"mean_plddt":80.0,"plddt_source":"esmfold"}' > "${gene}_WT.json"
    """
}

process PREDICT_STRUCTURE_MUT {
    tag "${gene}_${protein_change}"
    container "${params.structures_mode == 'boltz' ? params.image_gpu : params.image_cpu}"

    input:
    tuple val(gene), val(protein_change), path(fasta), path(precomputed_pdb), path(precomputed_meta)

    output:
    tuple val(gene), val(protein_change), path("${gene}_${protein_change}.pdb"), path("${gene}_${protein_change}.json"), emit: mut_struct

    script:
    def mode = params.structures_mode
    if (mode == 'boltz') {
        error "El backend 'boltz' requiere GPU y la imagen ${params.image_gpu} no está autorizada/disponible en local."
    }
    def precomp_arg = (mode == 'precomputed' && precomputed_pdb) ? "--structure ${precomputed_pdb}" : ""
    """
    predict_structure.py \\
        --fasta "${fasta}" \\
        --gene "${gene}" \\
        --protein-change "${protein_change}" \\
        --role "mut" \\
        --backend "${mode}" \\
        ${precomp_arg} \\
        --window ${params.domain_window} \\
        --out "${gene}_${protein_change}.pdb" \\
        --meta "${gene}_${protein_change}.json"
    """

    stub:
    """
    echo "ATOM      1  CA  MET A   1       0.000   0.000   0.000  1.00 80.00           C" > "${gene}_${protein_change}.pdb"
    echo '{"gene":"${gene}","protein_change":"${protein_change}","model_start":1,"model_resseq_start":1,"model_resseq_end":10,"mutation_resseq_model":5,"mean_plddt":80.0,"plddt_source":"esmfold"}' > "${gene}_${protein_change}.json"
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
