process FETCH_FASTA_WT {
    tag "${gene}"
    container "${params.image_cpu}"

    input:
    val gene

    output:
    tuple val(gene), path("${gene}_WT.fasta"), emit: wt_fasta

    script:
    """
    fetch_fasta.py \\
        --gene "${gene}" \\
        --protein-change "WT" \\
        --role "wt" \\
        --outdir .
    """

    stub:
    """
    echo ">${gene}_WT" > "${gene}_WT.fasta"
    echo "MKLLVVALLA" >> "${gene}_WT.fasta"
    """
}

process FETCH_FASTA_MUT {
    tag "${gene}_${protein_change}"
    container "${params.image_cpu}"

    input:
    tuple val(gene), val(protein_change), path(wt_fasta)

    output:
    tuple val(gene), val(protein_change), path("${gene}_${protein_change}.fasta"), emit: mut_fasta

    script:
    """
    fetch_fasta.py \\
        --gene "${gene}" \\
        --protein-change "${protein_change}" \\
        --role "mut" \\
        --wt-fasta "${wt_fasta}" \\
        --outdir .
    """

    stub:
    """
    echo ">${gene}_${protein_change}" > "${gene}_${protein_change}.fasta"
    echo "MKLLVVALLA" >> "${gene}_${protein_change}.fasta"
    """
}
