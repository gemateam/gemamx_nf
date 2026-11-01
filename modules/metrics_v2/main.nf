/*
 * Módulos de integración del pipeline V2.
 *
 * ASSEMBLE_V2  — toma los resultados precomputados de M3 (estructuras Boltz-1)
 *                y M4 (docking Vina) junto con las salidas en caliente de M1/M2
 *                y M5, y los ensambla en el árbol data/ del contrato.
 *
 * PUBLISH_V2   — sella la corrida generando run_manifest.json con checksums.
 */

process ASSEMBLE_V2 {
    tag "assemble_v2"
    container "${params.image_cpu}"

    publishDir "${params.outdir}", mode: 'copy', overwrite: true,
               enabled: !workflow.stubRun, saveAs: { fn ->
        fn.startsWith("stage/") ? fn.substring("stage/".length()) : fn
    }

    input:
    path top_variants
    path raw_mutations
    path mutation_stats
    path structural_metrics          // precomputado por calc_structural_metrics_romero.py
    path vina_affinities             // precomputado por run_docking_romero.py
    path clinical_summary            // generado por BUILD_CLINICAL_SUMMARY
    path clinical_metadata           // generado por EXTRACT_CLINICAL
    path struct_dir,      stageAs: "structures_src"
    path complex_dir,     stageAs: "complex_src"
    path results_dir,     stageAs: "results_src"
    path drug_catalog

    output:
    path "stage/data",                                              emit: data_dir
    path "stage/data/top_variants.json",                           emit: top_variants_out
    path "stage/data/raw_mutations.json",                          emit: raw_mutations_out
    path "stage/data/mutation_stats.json",                         emit: mutation_stats_out
    path "stage/data/structural_metrics.json",                     emit: structural_metrics_out
    path "stage/data/manifest_structures.json",                    emit: manifest_structures_out
    path "stage/data/docking/vina_affinities.json",                emit: vina_affinities_out
    path "stage/data/variant_clinical_summary.json", optional: true, emit: clinical_summary_out
    path "stage/data/clinical_metadata.json",        optional: true, emit: clinical_metadata_out
    path "stage/data/structures/*",                  optional: true, emit: structures_out
    path "stage/data/docking/complex/*",             optional: true, emit: complexes_out
    path "stage/data/docking/results/*",             optional: true, emit: poses_out

    script:
    """
    mkdir -p stage/data

    ingest_v2.py \\
        --top             "${top_variants}" \\
        --raw             "${raw_mutations}" \\
        --stats           "${mutation_stats}" \\
        --structural      "${structural_metrics}" \\
        --vina            "${vina_affinities}" \\
        --clinical        "${clinical_summary}" \\
        --struct-dir      structures_src \\
        --catalog         "${drug_catalog}" \\
        --outdir          stage/data

    # Copiar metadatos clínicos base
    cp "${clinical_metadata}" stage/data/clinical_metadata.json || true

    # Copiar complejos de docking
    mkdir -p stage/data/docking/complex
    cp -r complex_src/. stage/data/docking/complex/ || true

    # Copiar poses de docking (_out.pdbqt)
    mkdir -p stage/data/docking/results
    cp results_src/*_out.pdbqt stage/data/docking/results/ 2>/dev/null || true
    """

    stub:
    """
    mkdir -p stage/data/docking
    cp "${top_variants}"       stage/data/top_variants.json
    cp "${raw_mutations}"      stage/data/raw_mutations.json
    cp "${mutation_stats}"     stage/data/mutation_stats.json
    cp "${structural_metrics}" stage/data/structural_metrics.json
    cp "${vina_affinities}"    stage/data/docking/vina_affinities.json
    echo '{}' > stage/data/manifest_structures.json
    """
}


process PUBLISH_V2 {
    tag "${run_name}"
    container "${params.image_cpu}"

    publishDir "${params.outdir}",        mode: 'copy', overwrite: true,
               pattern: "run_manifest.json", enabled: !workflow.stubRun
    publishDir "${params.outdir}/data",   mode: 'copy', overwrite: true,
               pattern: "run_manifest.json", enabled: !workflow.stubRun

    input:
    path data_dir,  stageAs: "stage/data"
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
  "image_cpu":     "${params.image_cpu}",
  "image_docking": "${params.image_docking}",
  "image_gpu":     "${params.image_gpu}",
  "image_mlflow":  "${params.image_mlflow}"
}
IMAGES_EOF

    python3 << 'PYEOF'
import hashlib, json, pathlib, datetime

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
    "docking/vina_affinities.json",
    "variant_clinical_summary.json",
    "clinical_metadata.json",
]

files = {}
for name in contracts:
    p = pathlib.Path("stage/data") / name
    if p.exists():
        files[name] = sha256(str(p))

params  = json.loads(pathlib.Path("params.json").read_text())
images  = json.loads(pathlib.Path("images.json").read_text())

manifest = {
    "run_name":          "${run_name}",
    "published_at":      datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "git_commit":        "${commit_hash}",
    "pipeline_version":  "GEMAMX-V2-ROMERO",
    "dataset":           "Romero-Cordoba 2021 HM",
    "study_id":          "${params.study_id}",
    "params":            params,
    "images":            images,
    "files":             files,
    "contracts":         list(files.keys()),
}
pathlib.Path("run_manifest.json").write_text(
    json.dumps(manifest, indent=4, sort_keys=True))
print(f"run_manifest.json: {len(files)} contratos")
PYEOF
    """

    stub:
    """
    echo '{"run_name":"${run_name}","pipeline_version":"GEMAMX-V2-ROMERO"}' > run_manifest.json
    echo '{}' > params.json
    """
}
