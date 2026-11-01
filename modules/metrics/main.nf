process BUILD_JSONS {
    tag "contract_jsons"
    container "${params.image_cpu}"

    // publishDir copia el árbol data/ al outdir del host directamente.
    // Nextflow ejecuta el copy desde el orquestador (fuera del contenedor),
    // por lo que accede al filesystem del host sin restricciones.
    // En -stub-run no se publica nada: los JSON son placeholders ([]/{} y
    // estructuras vacías) y sobrescribirían el contrato vigente de results/data.
    publishDir "${params.outdir}", mode: 'copy', overwrite: true,
               enabled: !workflow.stubRun, saveAs: { fn ->
        // stage/data/foo.json → data/foo.json
        fn.startsWith("stage/") ? fn.substring("stage/".length()) : fn
    }

    input:
    path top_variants
    path raw_mutations
    path mutation_stats
    path drug_catalog
    path struct_files,  stageAs: "structures/*"
    path rmsd_files,    stageAs: "rmsd/*"
    path vina_files,    stageAs: "vina/*"
    path complex_files, stageAs: "complex/*"

    output:
    // Emitir los JSON del contrato como archivos individuales (no el directorio)
    // para evitar problemas de symlinks rotos entre contenedores.
    path "stage/data/top_variants.json",       emit: top_variants_out
    path "stage/data/structural_metrics.json", emit: structural_metrics
    path "stage/data/manifest_structures.json",emit: manifest_structures
    path "stage/data/raw_mutations.json",      emit: raw_mutations_out
    path "stage/data/mutation_stats.json",     emit: mutation_stats_out
    path "stage/data/docking/vina_affinities.json", emit: vina_affinities

    // Artefactos que la webapp consume además de los seis JSON: estructuras
    // (manifest_structures.json apunta a ellas), poses y complejos de docking.
    // Sin declararlos como output, publishDir no los copia al outdir.
    path "stage/data/structures/*",       optional: true, emit: structures_out
    path "stage/data/docking/results/*",  optional: true, emit: poses_out
    path "stage/data/docking/complex/*",  optional: true, emit: complexes_out

    script:
    """
    mkdir -p stage/data

    find vina -type l -o -type f -name "*_out.pdbqt" -exec cp {} vina/ \\; 2>/dev/null || true

    build_jsons.py \\
        --top "${top_variants}" \\
        --raw "${raw_mutations}" \\
        --stats "${mutation_stats}" \\
        --catalog "${drug_catalog}" \\
        \$(ls structures/*.json 2>/dev/null | sed 's/^/--structure-meta /' | tr '\\n' ' ') \\
        \$(ls rmsd/*.json 2>/dev/null | sed 's/^/--rmsd /' | tr '\\n' ' ') \\
        \$(ls vina/*_summary.json 2>/dev/null | sed 's/^/--vina /' | tr '\\n' ' ') \\
        \$(ls complex/*.pdb 2>/dev/null | sed 's/^/--complex /' | tr '\\n' ' ') \\
        --outdir stage/data
    """

    stub:
    """
    mkdir -p stage/data/docking
    echo '[]' > stage/data/top_variants.json
    echo '{}' > stage/data/structural_metrics.json
    echo '{}' > stage/data/manifest_structures.json
    echo '[]' > stage/data/raw_mutations.json
    echo '{}' > stage/data/mutation_stats.json
    echo '{}' > stage/data/docking/vina_affinities.json
    """
}

process PUBLISH {
    tag "${run_name}"
    container "${params.image_cpu}"

    // Publica run_manifest.json tanto en la raíz del outdir como en data/
    // para que la webapp lo encuentre en data/run_manifest.json.
    // Igual que BUILD_JSONS: un -stub-run no debe tocar el contrato vigente.
    publishDir "${params.outdir}",        mode: 'copy', overwrite: true,
               pattern: "run_manifest.json", enabled: !workflow.stubRun
    publishDir "${params.outdir}/data",   mode: 'copy', overwrite: true,
               pattern: "run_manifest.json", enabled: !workflow.stubRun

    input:
    // Solo los seis JSON del contrato — archivos planos, sin directorios
    path top_variants
    path structural_metrics
    path manifest_structures
    path raw_mutations
    path mutation_stats
    path vina_affinities
    val  run_name
    val  commit_hash

    output:
    path "run_manifest.json", emit: run_manifest
    path "params.json",       emit: run_params

    script:
    def params_json = groovy.json.JsonOutput.prettyPrint(
        groovy.json.JsonOutput.toJson(params)
    )
    """
    cat << 'PARAMS_EOF' > params.json
${params_json}
PARAMS_EOF

    cat << IMAGES_EOF > images.json
{
  "image_cpu": "${params.image_cpu}",
  "image_docking": "${params.image_docking}",
  "image_gpu": "${params.image_gpu}",
  "image_mlflow": "${params.image_mlflow}"
}
IMAGES_EOF

    # Calcular checksums de los contratos
    python3 << 'PYEOF'
import hashlib, json, pathlib, datetime, os, sys

def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()

contracts = [
    "top_variants.json",
    "structural_metrics.json",
    "manifest_structures.json",
    "raw_mutations.json",
    "mutation_stats.json",
    "vina_affinities.json",
]

files = {}
for name in contracts:
    p = pathlib.Path(name)
    if p.exists():
        files[name] = sha256(p)

params = json.loads(pathlib.Path("params.json").read_text())
images = json.loads(pathlib.Path("images.json").read_text())

manifest = {
    "run_name":     "${run_name}",
    "published_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "git_commit":   "${commit_hash}",
    "params":       params,
    "images":       images,
    "files":        files,
    "contracts":    contracts,
}
pathlib.Path("run_manifest.json").write_text(json.dumps(manifest, indent=4, sort_keys=True))
print(f"run_manifest.json escrito ({len(files)} contratos)")
PYEOF
    """

    stub:
    """
    echo '{"run_name":"${run_name}","commit":"${commit_hash}","files":{}}' > run_manifest.json
    echo '{}' > params.json
    """
}
