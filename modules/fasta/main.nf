process FETCH_FASTA_WT {
    tag "${gene}"
    container "${params.image_cpu}"

    input:
    // precomputed_fasta: ruta al FASTA WT local ([] si no hay)
    tuple val(gene), path(precomputed_fasta)

    output:
    tuple val(gene), path("${gene}_WT.fasta"), emit: wt_fasta

    script:
    def hasPrecomp = (precomputed_fasta && precomputed_fasta.toString() != 'null')
    if (hasPrecomp) {
        // Nextflow staged el archivo en el workdir; puede que ya tenga el nombre correcto.
        // Usamos python para una copia segura (no falla si src==dst).
        """
        python3 -c "
import shutil, pathlib
src = pathlib.Path('${precomputed_fasta}').resolve()
dst = pathlib.Path('${gene}_WT.fasta').resolve()
if src != dst:
    shutil.copy2(str(src), str(dst))
"
        """
    } else {
        """
        fetch_fasta.py \\
            --gene "${gene}" \\
            --protein-change "WT" \\
            --role "wt" \\
            --outdir .
        """
    }

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
    // precomputed_fasta: ruta al FASTA MUT local ([] si no hay)
    tuple val(gene), val(protein_change), path(wt_fasta), path(precomputed_fasta)

    output:
    tuple val(gene), val(protein_change), path("${gene}_${protein_change}.fasta"), emit: mut_fasta

    script:
    // Si hay un FASTA MUT precomputado, lo usamos directamente (validación de
    // la mutación ya fue realizada por el script de generación del V2).
    // Si no, generamos la secuencia mutante desde el WT con fetch_fasta.py.
    def usePrecomp = (precomputed_fasta && precomputed_fasta.toString() != 'null')
    if (usePrecomp) {
        // Nextflow staged el archivo en el workdir; puede que ya tenga el nombre
        // correcto. Usamos python para una copia segura (no falla si src==dst).
        """
        python3 -c "
import shutil, pathlib
src = pathlib.Path('${precomputed_fasta}').resolve()
dst = pathlib.Path('${gene}_${protein_change}.fasta').resolve()
if src != dst:
    shutil.copy2(str(src), str(dst))
"
        """
    } else {
        """
        fetch_fasta.py \\
            --gene "${gene}" \\
            --protein-change "${protein_change}" \\
            --role "mut" \\
            --wt-fasta "${wt_fasta}" \\
            --outdir .
        """
    }

    stub:
    """
    echo ">${gene}_${protein_change}" > "${gene}_${protein_change}.fasta"
    echo "MKLLVVALLA" >> "${gene}_${protein_change}.fasta"
    """
}
