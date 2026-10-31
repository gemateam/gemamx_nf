process PREP_LIGAND {
    tag "${drug}"
    container "${params.image_docking}"

    input:
    tuple val(drug), path(catalog)

    output:
    tuple val(drug), path("${drug}.pdbqt"), emit: ligand_pdbqt

    script:
    """
    prep_ligand.py \\
        --catalog "${catalog}" \\
        --drug "${drug}" \\
        --seed ${params.vina_seed} \\
        --out "${drug}.pdbqt" \\
        --meta "${drug}.json"
    """

    stub:
    """
    echo "REMARK  VINA LIGAND" > "${drug}.pdbqt"
    echo '{"drug":"${drug}","natoms":15}' > "${drug}.json"
    """
}

process PREP_RECEPTOR {
    tag "${target_id}"
    container "${params.image_docking}"

    input:
    tuple val(target_id), path(pdb_file), path(meta_json)

    output:
    tuple val(target_id), path("${target_id}.pdbqt"), path(meta_json), emit: receptor_pdbqt

    script:
    """
    prep_receptor.py \\
        --structure "${pdb_file}" \\
        --seed ${params.vina_seed} \\
        --out "${target_id}.pdbqt" \\
        --meta "${target_id}_prep.json"
    """

    stub:
    """
    echo "REMARK  VINA RECEPTOR" > "${target_id}.pdbqt"
    echo '{"target":"${target_id}"}' > "${target_id}_prep.json"
    """
}

process DOCK_CENTER {
    tag "${target_id}"
    container "${params.image_docking}"

    input:
    tuple val(target_id), path(receptor_pdbqt), path(meta_json)

    output:
    tuple val(target_id), path(receptor_pdbqt), path("${target_id}_box.json"), emit: target_box

    script:
    def mode = (params.box_center_mode == 'mutation' && target_id.endsWith('_WT')) ? 'centroid' : params.box_center_mode
    def meta_arg = mode == 'mutation' ? "--meta ${meta_json}" : ""
    """
    dock_center.py \\
        --receptor "${receptor_pdbqt}" \\
        --mode "${mode}" \\
        ${meta_arg} \\
        --box-size ${params.box_size} \\
        --out "${target_id}_box.json"
    """

    stub:
    """
    echo '{"center":[10.0, 10.0, 10.0],"box_size":${params.box_size},"mode":"${params.box_center_mode}"}' > "${target_id}_box.json"
    """
}

process RUN_VINA {
    tag "${target_id}_x_${drug}"
    container "${params.image_docking}"

    input:
    tuple val(target_id), path(receptor_pdbqt), path(box_json), val(drug), path(ligand_pdbqt)

    output:
    tuple val(target_id), val(drug), path("${target_id}_x_${drug}_summary.json"), emit: vina_summary
    path "${target_id}_x_${drug}_out.pdbqt", emit: vina_out_pdbqt
    path "${target_id}_x_${drug}_complex.pdb", emit: vina_complex_pdb

    script:
    """
    CENTER=\$(python3 -c "import json; b=json.load(open('${box_json}')); print(f\\"{b['center_x']} {b['center_y']} {b['center_z']}\\")")

    run_vina.py \\
        --receptor "${receptor_pdbqt}" \\
        --ligand "${ligand_pdbqt}" \\
        --center \${CENTER} \\
        --box-size ${params.box_size} \\
        --seed ${params.vina_seed} \\
        --exhaustiveness ${params.exhaustiveness} \\
        --num-modes ${params.num_modes} \\
        --cpu 1 \\
        --timeout ${params.vina_timeout_sec} \\
        --variant "${target_id}" \\
        --drug "${drug}" \\
        --out "${target_id}_x_${drug}_out.pdbqt" \\
        --log "${target_id}_x_${drug}_vina.log" \\
        --summary "${target_id}_x_${drug}_summary.json"

    merge_pose.py \\
        --receptor-pdbqt "${receptor_pdbqt}" \\
        --ligand-out-pdbqt "${target_id}_x_${drug}_out.pdbqt" \\
        --out "${target_id}_x_${drug}_complex.pdb"
    """

    stub:
    """
    echo '{"variant":"${target_id}","drug":"${drug}","affinity":-5.5,"modes":[{"mode":1,"affinity":-5.5}]}' > "${target_id}_x_${drug}_summary.json"
    echo "MODEL 1" > "${target_id}_x_${drug}_out.pdbqt"
    echo "ENDMDL" >> "${target_id}_x_${drug}_out.pdbqt"
    echo "ATOM   COMPLEX" > "${target_id}_x_${drug}_complex.pdb"
    """
}
