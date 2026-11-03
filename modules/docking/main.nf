/*
 * Helpers V2.1 — CSV de assets/ leídos en el orquestador (sin cambiar la aridad
 * de las tuplas de los procesos, así main.nf (V1) no se ve afectado).
 *
 *   loadSites(path, site_name)  -> [gene: "802;836;..."]
 *   loadPairing(path)           -> [gene: [drug: role]]
 */
def splitCsvLine(String line) {
    // Coma fuera de comillas; quita comillas envolventes.
    return line.split(/,(?=(?:[^"]*"[^"]*")*[^"]*$)/, -1).collect { it.trim().replaceAll(/^"|"$/, '') }
}

def parseCsv(String path) {
    def f = new File(path)
    if (!f.isFile()) {
        error "No existe el CSV: ${path}"
    }
    def lines = f.readLines('UTF-8').findAll { it.trim() }
    def header = splitCsvLine(lines[0])
    return lines.tail().collect { l ->
        def vals = splitCsvLine(l)
        if (vals.size() != header.size()) {
            error "CSV ${path}: fila con ${vals.size()} columnas, se esperaban ${header.size()}: ${l}"
        }
        [header, vals].transpose().collectEntries { k, v -> [(k): v] }
    }
}

def loadSites(String path, String siteName) {
    return parseCsv(path).findAll { it.site_name == siteName }.collectEntries { [(it.gene): it.residues] }
}

def loadPairing(String path) {
    def pairing = [:]
    parseCsv(path).each { r ->
        pairing.computeIfAbsent(r.gene, { k -> [:] }).put(r.drug, r.role)
    }
    return pairing
}

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
    def gene = target_id.tokenize('_')[0]
    def mode_args
    if (params.box_center_mode == 'binding_site') {
        // V2.1: centro = centroide de los residuos del bolsillo de la diana.
        if (!params.binding_sites) {
            error "box_center_mode=binding_site requiere --binding_sites (CSV gene,site_name,residues,...)"
        }
        def residues = loadSites(params.binding_sites.toString(), params.binding_site_name)[gene]
        if (!residues) {
            error "binding_sites no define el sitio '${params.binding_site_name}' para ${gene} (${target_id})"
        }
        mode_args = "--mode site-residues --site-residues '${residues}' --meta ${meta_json} --on-missing ${params.site_on_missing}"
    } else {
        def mode = (params.box_center_mode == 'mutation' && target_id.endsWith('_WT')) ? 'centroid' : params.box_center_mode
        def meta_arg = mode == 'mutation' ? "--meta ${meta_json}" : ""
        mode_args = "--mode ${mode} ${meta_arg}"
    }
    """
    dock_center.py \\
        --receptor "${receptor_pdbqt}" \\
        ${mode_args} \\
        --box-size ${params.box_size} \\
        --out "${target_id}_box.json"
    """

    stub:
    """
    echo '{"center_x":10.0,"center_y":10.0,"center_z":10.0,"box_size":${params.box_size},"mode":"${params.box_center_mode}"}' > "${target_id}_box.json"
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
    // V2.1: rol del par (on_target | off_target_control) y trazabilidad del sitio.
    // Sin target_drug_map / binding_site los argumentos quedan vacíos (V1 intacto).
    def gene = target_id.tokenize('_')[0]
    def role = params.target_drug_map ? (loadPairing(params.target_drug_map.toString())[gene]?.get(drug) ?: '') : ''
    def role_arg = role ? "--role ${role}" : ""
    def box_arg = (params.box_center_mode == 'binding_site') ? "--box-json ${box_json}" : ""
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
        ${role_arg} \\
        ${box_arg} \\
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
