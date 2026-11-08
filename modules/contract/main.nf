process VALIDATE_CONTRACT {
    tag "contract"
    container "${params.image_cpu}"

    input:
    // Directorio del bundle o lista vacía cuando la corrida no usa contrato.
    path contract_dir
    val  allow_curated

    output:
    path "contract_validation.json", emit: report

    script:
    def has_contract = contract_dir \
        && contract_dir != [] \
        && contract_dir.toString() != 'null' \
        && contract_dir.toString() != '[]'
    def allow_arg = (allow_curated == true || allow_curated == 'true') \
        ? '--allow-curated' : ''
    """
    if [ "${has_contract}" = "true" ]; then
        validate_contract.py \\
            --contract-dir "${contract_dir}" \\
            ${allow_arg} \\
            --json-out contract_validation.json
    else
        echo '{"status":"skipped","reason":"contract_dir no definido"}' > contract_validation.json
    fi
    """

    stub:
    """
    echo '{"status":"stub","valid":true}' > contract_validation.json
    """
}
