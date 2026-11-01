/*
 * ============================================================================
 * BOLTZ — predicción WT/MUT con Boltz-1 (solo GPU)
 * ============================================================================
 *
 * ESTADO: implementado y documentado, NO ejecutable en el equipo de desarrollo
 * (sin GPU). Pensado para YUCA (ACARUS, UNISON): 6 nodos GPU con AMD MI210
 * (64 GB HBM2e) y ROCm 6.2.3. Ver docs/BOLTZ_HPC.md.
 *
 * Requisitos:
 *   - GPU con >= 16 GB de VRAM (24 GB recomendado para 1000+ aa). En YUCA son
 *     MI210 (AMD): Boltz-1 se publica para CUDA, así que la ruta ROCm está por
 *     validar; si falla, `--accelerator cpu` sobre los 48 cores del nodo.
 *   - imagen params.image_gpu con `boltz` en el PATH
 *     (containers/gpu/Dockerfile, derivada de gemamx-gpu:1.0.0; en YUCA se usa
 *     el .sif de Apptainer)
 *   - internet si params.boltz_use_msa_server = true (servidor MSA de ColabFold);
 *     en un nodo sin salida, precalcular el MSA y pasarlo en el YAML.
 *
 * Activación (ver docs/BOLTZ_HPC.md § Activación):
 *   1. main.nf: incluir BOLTZ_WT/BOLTZ_MUT y usar la rama comentada.
 *   2. nextflow run . -profile hpc-yuca --structures_mode boltz
 *
 * GPU: la directiva `accelerator 1` es la que reserva la GPU; el flag concreto
 * lo pone el perfil (`--gpus all` con Docker local, `apptainer.runOptions =
 * '--rocm'` en YUCA), no el proceso.
 *
 * La salida replica la de PREDICT_STRUCTURE_*: PDB normalizado + sidecar JSON
 * (+ mmCIF para la webapp), de modo que ALIGN_WT_MUT, PREP_RECEPTOR y
 * BUILD_JSONS no cambian.
 */

process BOLTZ_WT {
    tag "${gene}_WT"
    container "${params.image_gpu}"
    accelerator 1

    input:
    tuple val(gene), path(fasta), val(window_center)

    output:
    tuple val(gene), path("${gene}_WT.pdb"), path("${gene}_WT.json"), emit: wt_struct
    path "${gene}_WT.cif", optional: true, emit: wt_cif

    script:
    def msa_arg = params.boltz_use_msa_server ? '--use_msa_server' : ''
    """
    prep_boltz_yaml.py \\
        --fasta "${fasta}" \\
        --gene "${gene}" \\
        --protein-change "WT" \\
        --role "wt" \\
        --window ${params.domain_window} \\
        ${window_center ? "--window-center ${window_center}" : ''} \\
        --out-yaml "${gene}_WT.yaml" \\
        --out-meta "${gene}_WT_prep.json"

    boltz predict "${gene}_WT.yaml" \\
        --out_dir boltz_out \\
        --cache /tmp/boltz-cache \\
        --seed ${params.boltz_seed} \\
        --accelerator gpu \\
        --output_format mmcif \\
        --num_workers 1 \\
        ${msa_arg}

    CIF=\$(find boltz_out -name '*_model_0.cif' -print -quit)
    if [ -z "\${CIF}" ]; then
        echo "ERROR: Boltz no generó ningún *_model_0.cif" >&2
        exit 1
    fi
    MODEL_START=\$(python3 -c "import json; print(json.load(open('${gene}_WT_prep.json'))['model_start'])")

    # Normalización común (PDB + sidecar + mmCIF, pLDDT desde el B-factor)
    predict_structure.py \\
        --fasta "${fasta}" \\
        --gene "${gene}" \\
        --protein-change "WT" \\
        --role "wt" \\
        --backend precomputed \\
        --structure "\${CIF}" \\
        --model-start "\${MODEL_START}" \\
        --out "${gene}_WT.pdb" \\
        --out-cif "${gene}_WT.cif" \\
        --meta "${gene}_WT.json"
    """
}

process BOLTZ_MUT {
    tag "${gene}_${protein_change}"
    container "${params.image_gpu}"
    accelerator 1

    input:
    tuple val(gene), val(protein_change), path(fasta)

    output:
    tuple val(gene), val(protein_change), path("${gene}_${protein_change}.pdb"), path("${gene}_${protein_change}.json"), emit: mut_struct
    path "${gene}_${protein_change}.cif", optional: true, emit: mut_cif

    script:
    def msa_arg = params.boltz_use_msa_server ? '--use_msa_server' : ''
    """
    prep_boltz_yaml.py \\
        --fasta "${fasta}" \\
        --gene "${gene}" \\
        --protein-change "${protein_change}" \\
        --role "mut" \\
        --window ${params.domain_window} \\
        --out-yaml "${gene}_${protein_change}.yaml" \\
        --out-meta "${gene}_${protein_change}_prep.json"

    boltz predict "${gene}_${protein_change}.yaml" \\
        --out_dir boltz_out \\
        --cache /tmp/boltz-cache \\
        --seed ${params.boltz_seed} \\
        --accelerator gpu \\
        --output_format mmcif \\
        --num_workers 1 \\
        ${msa_arg}

    CIF=\$(find boltz_out -name '*_model_0.cif' -print -quit)
    if [ -z "\${CIF}" ]; then
        echo "ERROR: Boltz no generó ningún *_model_0.cif" >&2
        exit 1
    fi
    MODEL_START=\$(python3 -c "import json; print(json.load(open('${gene}_${protein_change}_prep.json'))['model_start'])")

    predict_structure.py \\
        --fasta "${fasta}" \\
        --gene "${gene}" \\
        --protein-change "${protein_change}" \\
        --role "mut" \\
        --backend precomputed \\
        --structure "\${CIF}" \\
        --model-start "\${MODEL_START}" \\
        --out "${gene}_${protein_change}.pdb" \\
        --out-cif "${gene}_${protein_change}.cif" \\
        --meta "${gene}_${protein_change}.json"
    """
}
